"""Traducao de erros tecnicos pra mensagens que uma secretaria sem jargao
fiscal consegue entender e agir — instrucao da Etapa 2: "erros da API
traduzidos para mensagens compreensiveis". Ponto unico de traducao pra toda
a UI usar, em vez de cada tela inventar seu proprio texto de erro.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

import httpx

from app.core.documentos import DocumentoInvalido
from app.core.valores import ValorInvalido
from app.fiscal import api_nacional, assinador
from app.fiscal.dps_builder import CampoMuitoLongo

# Trechos de erro conhecidos da API nacional (vistos no spike) -> explicacao
# em portugues claro. Comparacao por substring, sem exigir o codigo exato.
_TRECHOS_CONHECIDOS = [
    ("E0714", "O certificado nao aceitou a assinatura da nota. Confira se o arquivo do certificado nao foi alterado e tente de novo."),
    ("E0310", "O codigo do tipo de servico nao existe pra essa data. Confira o 'modelo de servico' usado nesta nota."),
    ("E0312", "O codigo do tipo de servico nao pode mais ser usado nesta data. Atualize o 'modelo de servico'."),
    ("RNG6110", "Os dados do prestador ou o numero da nota estao com um formato que a Receita nao aceitou. Fale com o suporte."),
    ("RNG9997", "Falta uma informacao obrigatoria na nota (erro de formato). Fale com o suporte."),
    # Eventos de cancelamento (e101101) — docs/auditoria.md, Bloco 4.4
    ("E0822", "O prazo pra cancelar essa nota ja passou (prazo definido pela prefeitura, nao pelo programa). A nota continua valida — fale com seu contador sobre a melhor forma de corrigir isso (por exemplo, emitindo uma nota de ajuste)."),
    ("E0823", "Nao deu pra cancelar: o valor desta nota esta acima do limite que a prefeitura permite cancelar."),
    ("E0824", "Nao deu pra cancelar: falta identificar o tomador, exigido pela prefeitura pra esse tipo de cancelamento."),
    ("E0840", "Esta nota ja tem um cancelamento registrado na Receita — nao e possivel cancelar de novo."),
    ("E0845", "Esta nota ja foi cancelada (por substituicao) na Receita — nao e possivel cancelar de novo."),
    # Ampliacao da tabela (docs/auditoria.md, Bloco 6.3 — "qualquer codigo
    # fora da lista de 5 ainda cai no fallback generico"). Fonte: compilacao
    # de terceiros (nao a planilha oficial Anexo I linha-a-linha, que exigiria
    # abrir de novo o arquivo baixado numa sessao anterior) — cobre os casos
    # mais prováveis pro publico deste app (medico PJ, Simples Nacional,
    # emissao propria sem intermediario/obra). Se a Receita devolver um
    # codigo que pareca traduzido errado, confirmar contra o Anexo I oficial
    # antes de confiar cegamente na frase abaixo.
    ("E0001", "O layout de XML usado por este programa está desatualizado. Entre em contato com o suporte."),
    ("E0004", "Os dados de identificação desta nota (CNPJ, município ou série) não bateram com o cadastro do prestador."),
    ("E0008", "A data de emissão desta nota está no futuro — confira a data e hora do computador."),
    ("E0014", "Já existe uma nota com esse mesmo número — o programa evita isso automaticamente, tente emitir de novo."),
    ("E0037", "O município deste prestador ainda não está habilitado no Sistema Nacional de NFS-e."),
    ("E0038", "O convênio deste município com o Sistema Nacional de NFS-e está inativo no momento."),
    ("E0080", "O CNPJ do prestador está com formato inválido."),
    ("E0082", "Este CNPJ não foi encontrado ou está inativo na Receita Federal."),
    ("E0096", "O CPF do prestador está com formato inválido."),
    ("E0098", "Este CPF não foi encontrado ou está cancelado na Receita Federal."),
    ("E0116", "A inscrição municipal está com formato que a prefeitura não aceitou."),
    ("E0119", "Esta inscrição municipal não está autorizada a emitir NFS-e nesse município."),
    ("E0130", "O código do município (IBGE) informado é inválido."),
    ("E0148", "O e-mail do prestador está com formato inválido."),
    ("E0160", "A situação do prestador no Simples Nacional aqui no programa não bate com o que a Receita Federal tem cadastrado. Confira o regime cadastrado."),
    ("E0166", "Falta informar o regime de apuração do Simples Nacional para este prestador ME/EPP."),
    ("E0188", "O CNPJ do tomador está com formato inválido."),
    ("E0190", "O CNPJ do tomador não foi encontrado na Receita Federal."),
    ("E0202", "O prestador e o tomador não podem ser o mesmo CNPJ/CPF nesta nota."),
    ("E0204", "Como esta nota está marcada como retida na fonte, é obrigatório identificar o tomador com CPF/CNPJ."),
    ("E0206", "O CPF do tomador está com formato inválido."),
    ("E0207", "O CPF do tomador não foi encontrado na Receita Federal."),
    ("E0247", "O e-mail do tomador está com formato inválido."),
    ("E0330", "O código de tributação nacional deste serviço não existe na tabela oficial. Confira o 'modelo de serviço' usado."),
    ("E0331", "O código de tributação nacional deste serviço foi desativado. Atualize o 'modelo de serviço'."),
    ("E0333", "O código NBS deste serviço não existe na tabela oficial."),
    ("E0341", "Falta a descrição do serviço nesta nota."),
    ("E0390", "Falta informar o tipo de tributação do ISS nesta nota."),
    ("E0404", "O valor do serviço precisa ser maior que zero."),
    ("E0423", "Prestador MEI não pode ter alíquota de ISS preenchida nesta nota."),
    ("E0429", "A alíquota de ISS informada é maior que o permitido (5%). Confira o 'modelo de serviço'."),
    ("E0431", "A soma das retenções desta nota é maior que o valor do serviço — confira os percentuais de retenção."),
    ("E0432", "O valor líquido desta nota (depois das retenções) não pode ficar negativo."),
    ("E0438", "Este município não permite retenção de ISS na fonte."),
    ("E0439", "Pra marcar retenção de ISS é preciso informar a alíquota."),
    ("E0440", "O valor de ISS retido precisa ser maior que zero."),
    ("E0441", "Prestador MEI não pode ter retenção de ISS nesta nota."),
    ("E0449", "Retenção de ISS pelo tomador não é permitida pra prestador optante do Simples Nacional neste caso."),
    ("E0617", "Prestador não optante do Simples Nacional precisa informar a alíquota de ISS."),
    ("E0625", "Prestador optante do Simples Nacional (sem retenção) não deve informar alíquota de ISS — o ISS já vai no DAS."),
    ("E0667", "A soma das retenções federais (IRRF/PIS/COFINS/CSLL/INSS) é maior que o valor do serviço."),
    ("E0700", "O valor de IRRF retido precisa ser maior que zero e menor que o valor do serviço."),
    ("E0701", "O valor de CSLL retido precisa ser maior que zero e menor que o valor do serviço."),
    ("E0715", "O certificado digital usado para assinar esta nota está vencido."),
    ("E0716", "O certificado usado não é do padrão aceito (precisa ser A1 ICP-Brasil)."),
    ("E0718", "Este certificado digital não pertence ao CNPJ/CPF do prestador desta nota."),
    ("E1268", "Esta nota já foi enviada e aceita antes — não é possível enviar a mesma nota de novo."),
    ("E1294", "O prazo pra enviar esta nota pra Receita já passou."),
    ("E1300", "A alíquota de ISS informada é maior que o limite permitido (5%)."),
    # Bloqueio LOCAL (nunca chega a sair pra rede) -- app.core.fila.emitir_nota_real,
    # docs/auditoria-2.md secao 8.1: cod_tributacao_municipal de um modelo de
    # serviço antigo, cadastrado com 10 dígitos (formato inválido pro XSD
    # oficial, que exige exatamente 3).
    (
        "CTRIBMUN_REVISAO",
        "O 'código de tributação municipal' cadastrado no modelo de serviço desta nota está num "
        "formato antigo (10 dígitos) que a Receita não aceita mais — o certo agora são 3 dígitos, "
        "ou deixar em branco se a prefeitura não tiver um código próprio. Abra 'Modelos de serviço', "
        "edite o serviço indicado e corrija (ou apague) esse código antes de tentar emitir de novo.",
    ),
]


def mensagem_catchup(quantidade: int) -> str:
    """Notificação da bandeja quando o app estava fechado no dia da
    mensalidade (Etapa 3 item 1, espec §4: "PC desligado no dia -> emite na
    próxima abertura... comportamento documentado, não bug")."""
    if quantidade == 1:
        return "1 mensalidade atrasada foi emitida agora."
    return f"{quantidade} mensalidades atrasadas foram emitidas agora."


def mensagem_ciclo_automatico(total_emitidas: int, total_rejeitadas: int) -> Optional[str]:
    """Resumo pra notificação da bandeja de um ciclo do agendador (a cada
    15 min). Devolve None quando não há nada que valha notificar."""
    if total_emitidas == 0 and total_rejeitadas == 0:
        return None
    partes = []
    if total_emitidas:
        partes.append(f"{total_emitidas} nota(s) emitida(s)")
    if total_rejeitadas:
        partes.append(f"{total_rejeitadas} rejeitada(s)")
    return " e ".join(partes) + " agora."


def mensagem_certificado_vencendo(prestador_nome: str, dias_restantes: int) -> str:
    if dias_restantes <= 0:
        return f'O certificado de "{prestador_nome}" já venceu — emissões vão falhar até renovar.'
    if dias_restantes == 1:
        return f'O certificado de "{prestador_nome}" vence amanhã.'
    return f'O certificado de "{prestador_nome}" vence em {dias_restantes} dias.'


def traduzir_motivo_rejeicao(texto_original: str) -> str:
    """Mesma tabela de traducao de `traduzir_erro`, mas pra motivos ja
    guardados como texto no banco (notas.motivo_rejeicao) — usada pelo
    historico e pela tela de emissao avulsa, que nao tem mais a excecao
    original em maos, so a string salva."""
    for trecho, explicacao in _TRECHOS_CONHECIDOS:
        if trecho in texto_original:
            return explicacao

    if "HTTP 401" in texto_original or "HTTP 403" in texto_original:
        return (
            "A Receita recusou o acesso (não é um erro nos dados desta nota). "
            "O certificado provavelmente ainda não está autorizado para esse ambiente "
            "(homologação/produção) na Receita — confira o cadastro do certificado antes de tentar de novo."
        )

    return f"A Receita rejeitou esta nota: {texto_original}"


def traduzir_erro_cancelamento(texto_original: str) -> str:
    """Mesma tabela de _TRECHOS_CONHECIDOS, mas com um fallback escrito pro
    contexto de CANCELAMENTO (notas.erro_cancelamento) em vez de emissao —
    "a Receita rejeitou esta nota" confundiria, ja que a nota continua
    emitida e valida; o que falhou foi o pedido de cancelamento dela."""
    for trecho, explicacao in _TRECHOS_CONHECIDOS:
        if trecho in texto_original:
            return explicacao
    return f"A Receita nao aceitou o cancelamento desta nota: {texto_original}"


def traduzir_erro(excecao: BaseException) -> str:
    """Retorna uma frase curta em portugues claro pra mostrar na tela.
    Nunca mostra stacktrace nem termos como 'XML', 'schema' ou 'HTTP' pro
    usuario final."""
    texto_original = str(excecao)

    if isinstance(excecao, api_nacional.ErroValidacao):
        return traduzir_motivo_rejeicao(texto_original)

    if isinstance(excecao, api_nacional.ErroRede):
        return (
            "Não foi possível falar com o sistema da Receita agora (ele pode estar fora do ar). "
            "A nota ficou pendente e o programa vai tentar de novo sozinho daqui a pouco."
        )

    if isinstance(excecao, assinador.CertificadoNaoConfigurado):
        return "Este prestador ainda não tem um certificado configurado. Cadastre o certificado A1 primeiro."

    if isinstance(excecao, assinador.CertificadoExpirado):
        return texto_original  # ja e' uma frase pronta e clara, ver assinador.carregar_certificado

    if isinstance(excecao, (ValorInvalido, DocumentoInvalido, CampoMuitoLongo)):
        # Mensagem ja e' escrita em portugues claro pro usuario final (ver
        # app/core/valores.py e app/core/documentos.py) -- nao precisa do
        # prefixo generico "Algo deu errado" nem de traducao nenhuma.
        return texto_original

    if isinstance(excecao, ValueError) and any(
        trecho in texto_original.lower() for trecho in ("pfx", "pkcs12", "invalid password")
    ):
        return "Não deu pra abrir o certificado — confira se o arquivo está certo e se a senha digitada está correta."

    if isinstance(excecao, FileNotFoundError):
        return "Não encontrei o arquivo do certificado no caminho salvo. Ele pode ter sido movido ou apagado."

    if isinstance(excecao, httpx.TransportError):
        return "Sem conexão com a internet no momento. Confira a rede e tente de novo."

    if isinstance(excecao, sqlite3.OperationalError) and "locked" in texto_original.lower():
        return (
            "O banco de dados deste programa está sendo usado por outra janela ou instância aberta ao mesmo tempo. "
            "Feche as outras janelas do programa e tente de novo."
        )

    if isinstance(excecao, sqlite3.DatabaseError) and (
        "malformed" in texto_original.lower() or "corrupt" in texto_original.lower()
    ):
        return (
            "O arquivo de dados deste programa parece estar corrompido e não pôde ser lido. "
            "Não tente reparar sozinho — feche o programa e procure suporte antes de continuar usando, "
            "pra não arriscar perder o histórico de notas."
        )

    if isinstance(excecao, sqlite3.IntegrityError) and "unique" in texto_original.lower():
        return (
            "Duas emissões coincidiram no mesmo instante e geraram o mesmo número de nota. "
            "Tente emitir de novo — o programa já evita isso automaticamente na maioria dos casos."
        )

    return f"Algo deu errado: {texto_original}"
