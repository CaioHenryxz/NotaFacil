"""Fila de emissao (espec-mvp-emissor-nfse.md, secao 2 item 7 e secao 5).

    Gatilho -> grava na fila local com status=pendente
            -> monta XML da DPS -> assina (A1 local) -> POST /nfse
            -> sucesso: status=emitida, salva chave, baixa XML, organiza em disco
            -> erro de rede/5xx: mantem pendente, agenda retry
               (5 min -> 30 min -> 2 h -> a cada 6 h)
            -> erro de validacao (4xx): status=rejeitada + motivo legivel

`processar_fila` varre TODAS as notas pendentes prontas pra tentar (de
qualquer prestador — mesma excecao de escopo que repo.py documenta) e usa um
`emissor` injetavel: em producao e `emitir_nota_real` (assina + chama a API
real); em teste, uma dublê que simula rede caindo, sem tocar em
certificado/rede de verdade.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Callable, Dict, List, Optional

from app import repo
from app.core import email as email_service
from app.core import pastas
from app.core.backoff import BACKOFF, RETRY_RECORRENTE, proximo_atraso  # noqa: F401 -- reexportado (fila.BACKOFF etc. continuam validos)
from app.fiscal import api_nacional, assinador
from app.fiscal import danfse_builder
from app.fiscal import dps_builder as db
from app.fiscal import evento_builder as eb

EmissorCallable = Callable[[Dict, Dict, Dict, Dict], api_nacional.RespostaEmissao]
CanceladorCallable = Callable[[Dict, Dict], api_nacional.RespostaCancelamento]
ReconciliadorCallable = Callable[[Dict, Dict], api_nacional.RespostaConsultaDps]


def _valor_retido(nota: Dict, campo_retem: str, campo_aliquota: str) -> Optional[str]:
    """R$ retido = valor da nota * aliquota/100 — so' calcula se a retencao
    estiver ligada E tiver uma aliquota configurada (docs/auditoria.md,
    Bloco 1.6/2.4). Sem isso, retorna None e o campo correspondente do XML
    nem aparece (ver app.fiscal.dps_builder._montar_trib_fed)."""
    if not nota.get(campo_retem):
        return None
    aliquota = nota.get(campo_aliquota)
    if not aliquota:
        return None
    valor = Decimal(str(nota["valor"]))
    pct = Decimal(str(aliquota))
    return str((valor * pct / Decimal("100")).quantize(Decimal("0.01")))


def dados_dps_de_nota(prestador: Dict, tomador: Dict, nota: Dict, modelo: Dict, *, ambiente: str = "homologacao") -> db.DadosDPS:
    """Monta o DadosDPS (app/fiscal/dps_builder.py) a partir das linhas do
    banco. Simplificacao desta etapa: assume que o servico foi prestado no
    mesmo municipio do prestador (codigo_municipio_prestacao = prestador).
    Servico prestado em outro municipio fica pra quando a UI existir.

    As retencoes (docs/auditoria.md, Bloco 1.6/2.4) vem da propria `nota` —
    ela ja guarda o valor aplicado (copiado do tomador na emissao, ou
    sobrescrito so' pra essa nota; ver app/repo.py `criar_nota`/`retencoes`),
    nunca do tomador diretamente aqui, pra nao reabrir a decisao depois que a
    nota ja foi criada."""
    return db.DadosDPS(
        ambiente=ambiente,
        prestador=db.Prestador(
            documento=prestador["cnpj"],
            inscricao_municipal=prestador["im"],
            codigo_municipio=prestador["codigo_municipio"],
            opcao_simples_nacional=prestador["regime"],
            regime_especial_tributacao=prestador["regime_especial_tributacao"],
        ),
        tomador=db.Tomador(
            documento=tomador["doc"],
            nome=tomador["nome"],
            email=tomador.get("email"),
        ),
        servico=db.Servico(
            codigo_tributacao_nacional=modelo["cod_tributacao_nacional"],
            codigo_tributacao_municipal=modelo["cod_tributacao_municipal"],
            codigo_nbs=modelo["cod_nbs"],
            descricao=modelo["descricao"],
            codigo_municipio_prestacao=prestador["codigo_municipio"],
            valor=nota["valor"],
            aliquota_iss=modelo.get("aliquota"),
            # 2 = Retido pelo tomador (convenio/plano de saude reteve o ISS na
            # fonte) -- ver app.fiscal.dps_builder._pAliq_deve_ser_omitido:
            # com retencao, pAliq volta a ser OBRIGATORIO mesmo pro optante
            # do Simples Nacional (regras E0619/E0621).
            tipo_retencao_issqn="2" if nota.get("retem_iss") else "1",
            valor_retido_irrf=_valor_retido(nota, "retem_irrf", "aliquota_irrf"),
            valor_retido_pis=_valor_retido(nota, "retem_pis", "aliquota_pis"),
            valor_retido_cofins=_valor_retido(nota, "retem_cofins", "aliquota_cofins"),
            valor_retido_csll=_valor_retido(nota, "retem_csll", "aliquota_csll"),
            valor_retido_inss=_valor_retido(nota, "retem_inss", "aliquota_inss"),
        ),
        numeracao=db.Numeracao(serie=nota["serie"], numero_dps=nota["numero_dps"]),
    )


def emitir_nota_real(prestador: Dict, tomador: Dict, nota: Dict, modelo: Dict) -> api_nacional.RespostaEmissao:
    """Implementacao real do `emissor`: carrega o certificado (senha do
    keyring), assina a DPS e envia pra homologacao. E o que roda quando o app
    tiver um certificado A1 de verdade configurado."""
    if modelo.get("precisa_revisao_cod_trib_municipal"):
        # Bloqueio LOCAL, antes de gastar rede/certificado -- o codigo de
        # tributacao municipal deste modelo esta no formato antigo (10
        # digitos, invalido pro XSD oficial, docs/auditoria-2.md secao 8.1).
        # Levanta o mesmo ErroValidacao usado pra rejeicao 4xx da Receita
        # (ver api_nacional.py) pra reaproveitar o caminho de
        # `processar_fila` que ja marca a nota como 'rejeitada' com um
        # motivo legivel (ver app.core.mensagens._TRECHOS_CONHECIDOS).
        raise api_nacional.ErroValidacao(
            "CTRIBMUN_REVISAO: o codigo de tributacao municipal do modelo de "
            f'servico "{modelo.get("descricao", "")}" precisa ser revisado antes de emitir.'
        )
    chave, certificado, extras = assinador.carregar_certificado(prestador["id"], prestador["caminho_pfx"])
    dados = dados_dps_de_nota(prestador, tomador, nota, modelo)
    xml_assinado = assinador.assinar(dados, chave, certificado, extras)
    resposta = api_nacional.enviar_dps(xml_assinado, chave, certificado, extras, ambiente="homologacao")
    resposta.pdf_nfse = _obter_danfse(resposta, chave, certificado, extras)
    return resposta


def _obter_danfse(resposta: api_nacional.RespostaEmissao, chave_privada, certificado, extras) -> Optional[bytes]:
    """DANFSe (docs/auditoria-2.md, secao 9 -- NT-008/2026 v1.02): a API
    oficial (`api_nacional.buscar_danfse`) sera SUSPENSA em
    `danfse_builder.DATA_SUSPENSAO_API_OFICIAL` (03/08/2026, configuravel).

    Ate essa data: API oficial e' a fonte PRIMARIA (e' o layout oficial de
    verdade, devolvido pelo governo). Se ela responder, tambem geramos o
    DANFSe local so' pra COMPARAR (nunca pra salvar -- o PDF que vai pro
    disco continua sendo sempre o oficial enquanto ela estiver no ar),
    avisando no console se algo essencial divergir.

    A partir dessa data (ou se a API oficial falhar por rede antes dela):
    gerador local, unica fonte que sobra.

    Como sempre, PDF nunca e' obrigatorio pra nota contar como emitida --
    falhando os dois, devolve None (o XML ja e' o documento fiscal valido)."""
    hoje = dt.date.today()
    if hoje < danfse_builder.DATA_SUSPENSAO_API_OFICIAL:
        try:
            pdf_oficial = api_nacional.buscar_danfse(
                resposta.chave_acesso, chave_privada, certificado, extras, ambiente="homologacao"
            )
        except api_nacional.ErroRede:
            pdf_oficial = None  # DANFSe e sabidamente instavel (502/503) -- nao bloqueia a nota
        if pdf_oficial is not None:
            _comparar_com_gerador_local(resposta.xml_nfse, pdf_oficial, resposta.chave_acesso)
            return pdf_oficial

    try:
        return danfse_builder.montar_danfse_pdf(resposta.xml_nfse)
    except danfse_builder.DadosIncompletosParaDanfse as exc:
        print(f"[DANFSe] gerador local nao conseguiu montar o PDF da nota {resposta.chave_acesso}: {exc}")
        return None


def _comparar_com_gerador_local(xml_nfse: bytes, pdf_oficial: bytes, chave_acesso: str) -> None:
    """So' um alerta de console durante a transicao (nunca pode quebrar a
    emissao) -- confere se os dados essenciais batem entre o PDF oficial e
    o que o nosso gerador produziria pra MESMA NFS-e, pra pegar cedo
    qualquer divergencia de leiaute antes do dia 03/08/2026."""
    try:
        from io import BytesIO

        from pypdf import PdfReader

        pdf_local = danfse_builder.montar_danfse_pdf(xml_nfse)
        texto_oficial = PdfReader(BytesIO(pdf_oficial)).pages[0].extract_text() or ""
        texto_local = PdfReader(BytesIO(pdf_local)).pages[0].extract_text() or ""
    except Exception as exc:  # noqa: BLE001 -- comparacao e' so' diagnostico, nunca derruba a emissao
        print(f"[DANFSe] comparação com o gerador local falhou (nota {chave_acesso}): {exc}")
        return
    if chave_acesso not in texto_oficial:
        print(f"[DANFSe] AVISO: chave de acesso não apareceu no PDF OFICIAL da nota {chave_acesso} -- layout oficial mudou?")
    if chave_acesso not in texto_local:
        print(f"[DANFSe] AVISO: gerador local não incluiu a chave de acesso da nota {chave_acesso} -- revisar danfse_builder.")


def consultar_situacao_dps_real(prestador: Dict, nota: Dict) -> api_nacional.RespostaConsultaDps:
    """Implementacao real do `reconciliador`: recalcula o Id DETERMINISTICO
    da DPS (mesma formula de `dps_builder.montar_id_dps` usada na hora de
    montar/assinar a nota — nao depende de nenhuma resposta anterior) e
    pergunta pro governo se ela ja foi processada, ANTES de reenviar
    (docs/auditoria.md, Bloco 6.1)."""
    chave, certificado, extras = assinador.carregar_certificado(prestador["id"], prestador["caminho_pfx"])
    id_dps = db.montar_id_dps(
        prestador["codigo_municipio"], prestador["cnpj"], nota["serie"], nota["numero_dps"],
    )
    return api_nacional.consultar_dps(id_dps, chave, certificado, extras, ambiente="homologacao")


def processar_fila(
    repositorio: "repo.Repositorio",
    pasta_base,
    *,
    emissor: EmissorCallable = emitir_nota_real,
    reconciliador: ReconciliadorCallable = consultar_situacao_dps_real,
    agora: Optional[dt.datetime] = None,
    enviar_email: bool = True,
) -> List[Dict]:
    """Roda um ciclo da fila: pega toda nota pendente pronta pra tentar,
    chama `emissor` e trata o resultado. Retorna um resumo por nota — usado
    pelo demo.py e pelos testes pra inspecionar o que aconteceu.

    RECONCILIACAO (docs/auditoria.md, Bloco 6.1, achado critico): se esta ja
    e' pelo menos a segunda tentativa desta nota (`tentativas > 1`), existe a
    chance real de que a tentativa anterior tenha sido aceita pelo governo
    mas a resposta nunca chegou de volta (queda de rede DEPOIS do
    processamento, ANTES da confirmacao) — reenviar direto arriscaria
    duplicidade. Nesse caso, ANTES de chamar `emissor`, o ciclo pergunta pro
    governo (`reconciliador`) se essa DPS ja existe. Se existir, a nota e'
    marcada emitida com o que a consulta devolveu — nunca reenviada. Se a
    propria consulta falhar por rede, a nota so' fica pendente de novo
    (mesmo comportamento de sempre), nunca assume nada.

    Em caso de sucesso, dispara o e-mail ao tomador (Etapa 3, espec §5:
    "sucesso: ... dispara e-mail" e' parte do MESMO fluxo de emissao, nao um
    passo agendado a parte). Falha de e-mail nunca derruba a emissao — nota
    ja esta 'emitida' antes do e-mail ser sequer tentado."""
    agora = agora or dt.datetime.now()
    resultados: List[Dict] = []

    for nota in repositorio.listar_notas_pendentes_prontas_para_tentar(agora):
        prestador = repositorio.obter_prestador(nota["prestador_id"])
        tomador = repositorio.obter_tomador(nota["prestador_id"], nota["tomador_id"])
        modelo = repositorio.obter_modelo(nota["prestador_id"], nota["modelo_id"])

        repositorio.incrementar_tentativa(nota["prestador_id"], nota["id"])
        nota = repositorio.obter_nota(nota["prestador_id"], nota["id"])

        if nota["tentativas"] > 1:
            try:
                consulta = reconciliador(prestador, nota)
            except api_nacional.ErroRede as exc:
                proxima = agora + proximo_atraso(nota["tentativas"])
                repositorio.marcar_para_retry(nota["prestador_id"], nota["id"], proxima_tentativa_em=proxima)
                resultados.append({
                    "nota_id": nota["id"], "status": "pendente",
                    "proxima_tentativa_em": proxima, "erro": str(exc), "etapa": "reconciliacao",
                })
                continue
            if consulta.encontrada:
                # DANFSe (PDF) nao e' buscado aqui de proposito -- e' so'
                # facilidade visual (ver docstring de `buscar_danfse`), e
                # duplicar o carregamento do certificado so' pra isso deixaria
                # o caminho de reconciliacao mais fragil de testar. O XML ja
                # e' o documento fiscal valido; o PDF fica ausente nesta nota
                # (nao impede nada, mesma logica de qualquer falha de DANFSe).
                xml_bytes = consulta.xml_nfse or b""
                xml_path, pdf_path = pastas.salvar_nota(
                    pasta_base, prestador["nome_exibicao"], numero=nota["numero_dps"],
                    nome_tomador=tomador["nome"], valor=nota["valor"], data_emissao=agora.date(),
                    xml_bytes=xml_bytes, pdf_bytes=None, pasta_nome=prestador.get("pasta_nome"),
                )
                repositorio.marcar_emitida(
                    nota["prestador_id"], nota["id"], chave_acesso=consulta.chave_acesso or "",
                    xml_conteudo=xml_bytes.decode("utf-8", errors="replace"),
                    xml_path=str(xml_path), pdf_path=str(pdf_path) if pdf_path else None, emitida_em=agora,
                )
                resultados.append({
                    "nota_id": nota["id"], "status": "emitida", "reconciliada": True,
                    "chave_acesso": consulta.chave_acesso, "xml_path": str(xml_path),
                })
                continue
            # nao encontrada: a tentativa anterior realmente nao chegou no
            # governo -- segue pro fluxo normal de emissao abaixo, com seguranca.

        try:
            resposta = emissor(prestador, tomador, nota, modelo)
        except api_nacional.ErroValidacao as exc:
            repositorio.marcar_rejeitada(nota["prestador_id"], nota["id"], motivo=str(exc))
            resultados.append({"nota_id": nota["id"], "status": "rejeitada", "motivo": str(exc)})
            continue
        except api_nacional.ErroRede as exc:
            proxima = agora + proximo_atraso(nota["tentativas"])
            repositorio.marcar_para_retry(nota["prestador_id"], nota["id"], proxima_tentativa_em=proxima)
            resultados.append({
                "nota_id": nota["id"], "status": "pendente",
                "proxima_tentativa_em": proxima, "erro": str(exc),
            })
            continue

        xml_path, pdf_path = pastas.salvar_nota(
            pasta_base,
            prestador["nome_exibicao"],
            numero=nota["numero_dps"],
            nome_tomador=tomador["nome"],
            valor=nota["valor"],
            data_emissao=agora.date(),
            xml_bytes=resposta.xml_nfse,
            pdf_bytes=resposta.pdf_nfse,
            pasta_nome=prestador.get("pasta_nome"),
        )
        repositorio.marcar_emitida(
            nota["prestador_id"], nota["id"],
            chave_acesso=resposta.chave_acesso,
            xml_conteudo=resposta.xml_nfse.decode("utf-8", errors="replace"),
            xml_path=str(xml_path),
            pdf_path=str(pdf_path) if pdf_path else None,
            emitida_em=agora,
        )
        resultados.append({
            "nota_id": nota["id"], "status": "emitida",
            "chave_acesso": resposta.chave_acesso, "xml_path": str(xml_path),
        })

        if enviar_email:
            nota_emitida = repositorio.obter_nota(nota["prestador_id"], nota["id"])
            try:
                email_service.enviar_nota_email(repositorio, prestador, tomador, nota_emitida)
            except Exception:  # noqa: BLE001 — e-mail NUNCA pode derrubar a emissao
                pass

    return resultados


def criar_notas_das_recorrencias_do_dia(repositorio: "repo.Repositorio", hoje: dt.date) -> List[int]:
    """Botao [Emitir todas] do painel "Meu Dia" (espec, secao 2 item 1b) e
    motor do agendador (Etapa 3, core/agendador.py): cria uma nota 'pendente'
    pra cada mensalidade cujo dia_do_mes bate com `hoje` e que ainda nao foi
    emitida NESTE MES (evita duplicar se clicado 2x, ou se o catch-up de um
    dia atrasado rodar depois do dia normal). So CRIA — quem efetivamente
    tenta emitir e' o proximo `processar_fila`."""
    criadas: List[int] = []
    for m in repositorio.dados_meu_dia(hoje)["mensalidades_hoje"]:
        if m["ja_emitida_no_mes"]:
            continue
        # emissao automatica nunca tem "sobrescrever so' nesta nota" (nao ha
        # ninguem olhando) -- sempre usa o padrao do tomador (docs/auditoria.md,
        # Bloco 1.6/2.4: "a regra costuma ser fixa por convenio").
        tomador = repositorio.obter_tomador(m["prestador_id"], m["tomador_id"])
        retencoes = {campo: tomador[campo] for campo in repo.CAMPOS_RETENCAO} if tomador else None
        nota_id = repositorio.criar_nota(
            m["prestador_id"], tomador_id=m["tomador_id"], modelo_id=m["modelo_id"],
            valor=m["valor"], recorrencia_id=m["id"], retencoes=retencoes,
        )
        criadas.append(nota_id)
    return criadas


def cancelar_nfse_real(prestador: Dict, nota: Dict) -> api_nacional.RespostaCancelamento:
    """Implementacao real do `cancelador`: monta e assina o evento e101101 e
    envia pra Sefin Nacional. So' retorna em caso de confirmacao de verdade —
    ErroRede/ErroValidacao propagam pra `processar_cancelamentos` decidir."""
    chave, certificado, extras = assinador.carregar_certificado(prestador["id"], prestador["caminho_pfx"])
    dados = eb.DadosEventoCancelamento(
        ambiente="homologacao",
        chave_nfse=nota["chave_acesso"],
        documento_autor=prestador["cnpj"],
        codigo_motivo=nota["cod_motivo_cancelamento"],
        descricao_motivo=nota.get("motivo_cancelamento_texto"),
    )
    xml_assinado = eb.montar_e_assinar_evento(dados, chave, certificado, extras)
    return api_nacional.cancelar_nfse(
        nota["chave_acesso"], xml_assinado, chave, certificado, extras, ambiente="homologacao",
    )


def processar_cancelamentos(
    repositorio: "repo.Repositorio",
    *,
    cancelador: CanceladorCallable = cancelar_nfse_real,
    agora: Optional[dt.datetime] = None,
) -> List[Dict]:
    """Roda um ciclo da fila de CANCELAMENTO: pega toda nota em
    'cancelamento_pendente' pronta pra tentar, chama `cancelador` e trata o
    resultado (docs/auditoria.md, Bloco 4.4 — versao anterior desta funcao
    nunca avisava o governo, so' movia arquivo local).

        sucesso: status=cancelada, guarda protocolo, MOVE arquivo pra Canceladas/
        erro de rede: mantem cancelamento_pendente, agenda retry (mesmo backoff da emissao)
        erro de validacao (fora do prazo, ja cancelada etc.): volta pra emitida,
            guarda o motivo pra mostrar mensagem clara — nunca fica preso
            "pendente" pra sempre nem vira "cancelada" sem confirmacao.
    """
    agora = agora or dt.datetime.now()
    resultados: List[Dict] = []

    for nota in repositorio.listar_cancelamentos_pendentes_prontos_para_tentar(agora):
        prestador = repositorio.obter_prestador(nota["prestador_id"])

        repositorio.incrementar_tentativa(nota["prestador_id"], nota["id"])
        nota = repositorio.obter_nota(nota["prestador_id"], nota["id"])

        try:
            resposta = cancelador(prestador, nota)
        except api_nacional.ErroValidacao as exc:
            repositorio.reverter_cancelamento(nota["prestador_id"], nota["id"], motivo_falha=str(exc))
            resultados.append({"nota_id": nota["id"], "status": repo.STATUS_EMITIDA, "erro_cancelamento": str(exc)})
            continue
        except api_nacional.ErroRede as exc:
            proxima = agora + proximo_atraso(nota["tentativas"])
            repositorio.agendar_retry_cancelamento(nota["prestador_id"], nota["id"], proxima_tentativa_em=proxima)
            resultados.append({
                "nota_id": nota["id"], "status": repo.STATUS_CANCELAMENTO_PENDENTE,
                "proxima_tentativa_em": proxima, "erro": str(exc),
            })
            continue

        novo_xml, novo_pdf = pastas.cancelar_nota(nota["xml_path"], nota.get("pdf_path"))
        repositorio.marcar_cancelamento_confirmado(
            nota["prestador_id"], nota["id"],
            protocolo=resposta.protocolo, confirmado_em=resposta.confirmado_em,
            xml_path=str(novo_xml), pdf_path=str(novo_pdf) if novo_pdf else None,
        )
        resultados.append({
            "nota_id": nota["id"], "status": repo.STATUS_CANCELADA, "protocolo": resposta.protocolo,
        })

    return resultados


def solicitar_cancelamento(
    repositorio: "repo.Repositorio", prestador_id: int, nota_id: int, *,
    cod_motivo: str, motivo_texto: Optional[str] = None,
    cancelador: CanceladorCallable = cancelar_nfse_real,
) -> Dict:
    """Fluxo completo pedido pelo usuario: valida (so' cancela nota EMITIDA —
    repositorio.iniciar_cancelamento ja bloqueia nota ja cancelada/pendente),
    marca 'cancelamento_pendente' e tenta IMEDIATAMENTE uma vez — mesma logica
    de `criar_nota` + `processar_fila` na emissao avulsa. O resultado devolvido
    reflete o que REALMENTE aconteceu (cancelada | cancelamento_pendente |
    emitida-com-erro_cancelamento), nunca assume sucesso."""
    repositorio.iniciar_cancelamento(prestador_id, nota_id, cod_motivo=cod_motivo, motivo_texto=motivo_texto)
    resultados = processar_cancelamentos(repositorio, cancelador=cancelador)
    for r in resultados:
        if r["nota_id"] == nota_id:
            return r
    nota_atual = repositorio.obter_nota(prestador_id, nota_id)
    return {"nota_id": nota_id, "status": nota_atual["status"]}
