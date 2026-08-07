"""Unico ponto de acesso ao SQLite local (espec-mvp-emissor-nfse.md, secao 6).

Regra de ouro (espec, secao 6, ponytail do Rafael): "toda query da UI filtra
por prestador_id numa camada unica de acesso (repo.py) — a tela nunca monta
SQL". Nenhum outro modulo deste projeto deve abrir uma conexao sqlite3 ou
escrever uma string SQL. Toda funcao que le/grava dado de um prestador exige
prestador_id e o usa no WHERE — e a unica forma barata de garantir que os
dados de um prestador nunca vazem para outro (nem sequer por um bug de tela).

As UNICAS excecoes deliberadas sao `listar_notas_pendentes_prontas_para_tentar`
e `listar_notas_email_falhou_prontas_para_tentar` (usadas pelo agendador em
core/fila.py e core/email.py) e `dados_meu_dia` (usada pela tela "Meu Dia" da
UI, e que agora tambem carrega `sugestoes_de_mensalidade`) — todas varrem
TODOS os prestadores de uma vez, leitura agregada e somente leitura, sem
qualquer escrita fora do escopo de prestador_id de cada linha. E exatamente o
carve-out que a espec, secao 6, descreve pro painel "Meu Dia": "agrega todos,
mas e read-only + acoes em lote".

Colunas alem das literalmente listadas na espec (ex.: codigo_municipio e
caminho_pfx em prestadores; cod_tributacao_municipal e cod_nbs em
modelos_servico) foram acrescentadas porque o layout da DPS validado no
spike (app/fiscal/dps_builder.py) exige esses campos — sem eles nenhuma nota
sai do jeito que a Sefin Nacional aceita.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

STATUS_PENDENTE = "pendente"
STATUS_EMITIDA = "emitida"
STATUS_REJEITADA = "rejeitada"
STATUS_CANCELADA = "cancelada"
# Cancelamento pedido, aguardando confirmacao do governo (evento e101101) —
# NUNCA vira 'cancelada' sozinho; so' fila.processar_cancelamentos faz essa
# transicao, e so' com resposta de sucesso da API (docs/auditoria.md, Bloco 4.4).
STATUS_CANCELAMENTO_PENDENTE = "cancelamento_pendente"

EMAIL_NAO_ENVIADO = "nao_enviado"
EMAIL_ENVIADO = "enviado"
EMAIL_FALHOU = "falhou"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prestadores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_exibicao TEXT NOT NULL,
    cnpj TEXT NOT NULL,                        -- CNPJ ou CPF do prestador, so digitos
    im TEXT NOT NULL,                          -- inscricao municipal
    codigo_municipio TEXT NOT NULL,            -- codigo IBGE (7 digitos) do municipio emissor
    regime TEXT NOT NULL DEFAULT '1',          -- opSimpNac: 1 Nao optante | 2 MEI | 3 ME/EPP
    regime_especial_tributacao TEXT NOT NULL DEFAULT '0',
    caminho_pfx TEXT,                          -- caminho do .pfx importado no onboarding
    cor TEXT,
    pasta_nome TEXT,                           -- override do nome da pasta (senao usa nome_exibicao)
    cert_venc_em TEXT,                         -- data (ISO) de vencimento do certificado A1
    ativo INTEGER NOT NULL DEFAULT 1,          -- 0 = inativado (nunca apagado -- docs/auditoria.md, Bloco 4.1)
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tomadores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prestador_id INTEGER NOT NULL REFERENCES prestadores(id),
    doc TEXT NOT NULL,                         -- CNPJ ou CPF, so digitos
    nome TEXT NOT NULL,
    email TEXT,
    telefone TEXT,
    endereco TEXT,
    criado_em TEXT NOT NULL DEFAULT (datetime('now')),
    -- Retencoes PADRAO deste tomador (docs/auditoria.md, Bloco 1.6/2.4) --
    -- "a regra costuma ser fixa por convenio" (Unimed sempre retem X, etc.).
    -- Uma nota individual pode SOBRESCREVER isso (ver colunas espelhadas em
    -- `notas`, abaixo) -- estas aqui sao so o valor-padrao pro cadastro.
    retem_irrf INTEGER NOT NULL DEFAULT 0,
    aliquota_irrf TEXT,     -- % (ex.: "1.50") -- vRetIRRF = valor * aliquota/100
    retem_pis INTEGER NOT NULL DEFAULT 0,
    aliquota_pis TEXT,      -- % -- soma com cofins+csll dentro de vRetCSLL (ver dps_builder)
    retem_cofins INTEGER NOT NULL DEFAULT 0,
    aliquota_cofins TEXT,
    retem_csll INTEGER NOT NULL DEFAULT 0,
    aliquota_csll TEXT,
    retem_inss INTEGER NOT NULL DEFAULT 0,
    aliquota_inss TEXT,     -- % -- vRetCP
    retem_iss INTEGER NOT NULL DEFAULT 0, -- liga tpRetISSQN=2 (retido pelo tomador); sem % propria, usa a aliquota do modelo de servico
    ativo INTEGER NOT NULL DEFAULT 1      -- 0 = inativado (nunca apagado -- docs/auditoria.md, Bloco 4.1)
);

CREATE TABLE IF NOT EXISTS modelos_servico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prestador_id INTEGER NOT NULL REFERENCES prestadores(id),
    descricao TEXT NOT NULL,
    cod_tributacao_nacional TEXT NOT NULL,     -- cTribNac, 6 digitos (LC 116/2003)
    -- cTribMun: desdobro MUNICIPAL do ISSQN, OPCIONAL na nota (XSD oficial,
    -- TCCServ: minOccurs="0"); 3 digitos quando informado (TCCodTribMun,
    -- tiposSimples_v1.01.xsd: pattern "[0-9]{3}") -- NAO sao 10 digitos, era
    -- bug (docs/auditoria-2.md, secao 8.1). "" = prefeitura sem desdobro
    -- proprio, campo fica fora do XML (ver app.fiscal.dps_builder). Coluna
    -- continua NOT NULL (usa "" pra "nao informado") pra nao precisar
    -- recriar a tabela so' pra permitir NULL.
    cod_tributacao_municipal TEXT NOT NULL,
    cod_nbs TEXT NOT NULL,                     -- cNBS, 9 digitos (Nomenclatura Brasileira de Servicos)
    valor_padrao TEXT NOT NULL,
    aliquota TEXT,                             -- pAliq; deixar NULL se o municipio ja parametriza
    -- 1 = cod_tributacao_municipal ficou de um cadastro antigo (10 digitos,
    -- formato errado) e precisa de revisao antes de emitir com este modelo
    -- (docs/auditoria-2.md, secao 8.1) -- recalculado a cada
    -- criar/atualizar_modelo_servico, nunca setado a mao pela UI.
    precisa_revisao_cod_trib_municipal INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recorrencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prestador_id INTEGER NOT NULL REFERENCES prestadores(id),
    tomador_id INTEGER NOT NULL REFERENCES tomadores(id),
    modelo_id INTEGER NOT NULL REFERENCES modelos_servico(id),
    valor TEXT NOT NULL,
    dia_do_mes INTEGER NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prestador_id INTEGER NOT NULL REFERENCES prestadores(id),
    tomador_id INTEGER NOT NULL REFERENCES tomadores(id),
    modelo_id INTEGER NOT NULL REFERENCES modelos_servico(id),
    recorrencia_id INTEGER REFERENCES recorrencias(id),  -- preenchido quando a nota veio de uma mensalidade
    valor TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente',   -- pendente|emitida|rejeitada|cancelada
    serie TEXT NOT NULL DEFAULT '1',
    numero_dps TEXT NOT NULL,
    chave_acesso TEXT,
    xml_conteudo TEXT,                         -- XML da NFS-e (retornado pela API)
    xml_path TEXT,
    pdf_path TEXT,
    motivo_rejeicao TEXT,
    tentativas INTEGER NOT NULL DEFAULT 0,
    proxima_tentativa_em TEXT,
    criada_em TEXT NOT NULL DEFAULT (datetime('now')),
    emitida_em TEXT,
    email_status TEXT NOT NULL DEFAULT 'nao_enviado',  -- nao_enviado|enviado|falhou (Etapa 3)
    email_erro TEXT,
    -- Retry automatico de e-mail falhado (mesmo espirito da fila de emissao,
    -- item 2 da lista de automacoes pedida pelo usuario): backoff identico
    -- (app.core.backoff), rodado a cada ciclo do agendador, sem a secretaria
    -- precisar notar e clicar "Reenviar" na mao.
    email_tentativas INTEGER NOT NULL DEFAULT 0,
    proxima_tentativa_email_em TEXT,
    cod_motivo_cancelamento TEXT,   -- cMotivo do evento e101101: 1 Erro na Emissao | 2 Servico nao Prestado | 9 Outros
    motivo_cancelamento_texto TEXT, -- xMotivo (obrigatorio so' quando cod_motivo=9)
    erro_cancelamento TEXT,         -- ultimo motivo de RECUSA do cancelamento (prazo expirado, ja cancelada etc.)
    protocolo_cancelamento TEXT,    -- infEvento/id devolvido pelo governo na confirmacao
    cancelamento_confirmado_em TEXT,-- infEvento/dhProc devolvido pelo governo na confirmacao
    -- Retencoes APLICADAS nesta nota especifica (docs/auditoria.md, Bloco
    -- 1.6/2.4) -- copiadas do tomador no momento da emissao, mas o usuario
    -- pode sobrescrever so' pra esta nota (pedido explicito: "permitir
    -- sobrescrever so' naquela nota"), sem alterar o cadastro do tomador.
    retem_irrf INTEGER NOT NULL DEFAULT 0,
    aliquota_irrf TEXT,
    retem_pis INTEGER NOT NULL DEFAULT 0,
    aliquota_pis TEXT,
    retem_cofins INTEGER NOT NULL DEFAULT 0,
    aliquota_cofins TEXT,
    retem_csll INTEGER NOT NULL DEFAULT 0,
    aliquota_csll TEXT,
    retem_inss INTEGER NOT NULL DEFAULT 0,
    aliquota_inss TEXT,
    retem_iss INTEGER NOT NULL DEFAULT 0,
    UNIQUE (prestador_id, serie, numero_dps)
);

CREATE TABLE IF NOT EXISTS config (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
"""


def _linha_para_dict(linha: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    return dict(linha) if linha is not None else None


def _iso(momento: Optional[dt.datetime]) -> Optional[str]:
    return momento.isoformat(sep=" ") if momento is not None else None


def _precisa_revisao_cod_trib_municipal(cod_tributacao_municipal: str) -> bool:
    """cTribMun e' opcional (3 digitos quando informado -- ver comentario do
    schema, docs/auditoria-2.md secao 8.1). "" = nao informado, tudo bem;
    qualquer outra coisa que nao sejam exatamente 3 digitos numericos precisa
    de revisao antes que este modelo possa ser usado numa emissao real
    (ver app.core.fila.emitir_nota_real)."""
    valor = (cod_tributacao_municipal or "").strip()
    return bool(valor) and not (len(valor) == 3 and valor.isdigit())


def _exigir_dia_do_mes_valido(dia_do_mes: int) -> None:
    """1-28 -- existe em TODO mes, nunca cai em fevereiro/abril/junho/etc.
    sem esse dia (docs/auditoria.md, Bloco 3, item 5). A UI (QSpinBox/input
    range="1..28") ja trava isso, mas a API crua nao passava por nenhuma
    tela -- defesa em profundidade, mesmo padrao ja usado pra aliquota do
    Simples e pras retencoes."""
    if not 1 <= int(dia_do_mes) <= 28:
        raise ValueError("O dia do mês da mensalidade precisa ser entre 1 e 28 (existe em todo mês).")


# Retencoes na fonte (docs/auditoria.md, Bloco 1.6/2.4) — os mesmos 11 campos
# existem em `tomadores` (valor-padrao "costuma ser fixo por convenio") e em
# `notas` (aplicado a uma nota especifica, podendo sobrescrever o padrao do
# tomador so' naquela nota). Ver app/fiscal/dps_builder.py pra como isso vira
# tribFed no XML (vRetIRRF, vRetCSLL somado, vRetCP) e tpRetISSQN.
CAMPOS_RETENCAO = (
    "retem_irrf", "aliquota_irrf", "retem_pis", "aliquota_pis",
    "retem_cofins", "aliquota_cofins", "retem_csll", "aliquota_csll",
    "retem_inss", "aliquota_inss", "retem_iss",
)


def _normalizar_retencoes(retencoes: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Preenche os 11 campos de retencao com default seguro (nao retido) pra
    quem nao informar nada — nunca deixa um campo faltando por engano."""
    retencoes = retencoes or {}
    normalizado: Dict[str, Any] = {}
    for campo in CAMPOS_RETENCAO:
        if campo.startswith("retem_"):
            normalizado[campo] = int(bool(retencoes.get(campo, False)))
        else:
            normalizado[campo] = retencoes.get(campo) or None
    return normalizado


class Repositorio:
    """Uma instancia = uma conexao com um arquivo .db. Toda leitura/escrita
    do app passa por metodos desta classe — nenhum outro modulo importa
    sqlite3 nem escreve SQL."""

    def __init__(self, caminho_db: Union[str, Path]):
        self.caminho_db = str(caminho_db)
        self._conn = sqlite3.connect(self.caminho_db, timeout=10.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        # WAL (docs/auditoria.md, Bloco 6.5): permite um escritor + varios
        # leitores ao mesmo tempo sem "database is locked" -- o modo padrao
        # (rollback journal) trava o banco inteiro pro menor conflito. Nao
        # elimina 100% o risco de duas instancias escrevendo ao mesmo tempo
        # (isso e' resolvido pela trava de instancia unica, ver app/main.py),
        # mas cobre o caso comum de uma tela lendo enquanto outra grava.
        # `:memory:` nao suporta WAL (fica em modo "memory" mesmo) -- os
        # testes usam `:memory:` e continuam funcionando normalmente.
        self._conn.execute("PRAGMA journal_mode = WAL")
        # busy_timeout (em ms): se o banco estiver momentaneamente ocupado
        # por outra conexao, espera ate 10s tentando de novo sozinho antes de
        # levantar `sqlite3.OperationalError: database is locked` -- cobre a
        # colisao rara em vez de estourar erro na cara do usuario.
        self._conn.execute("PRAGMA busy_timeout = 10000")
        self._migrar()

    # Colunas adicionadas depois que as tabelas ja existiam em bancos de
    # clientes reais — `CREATE TABLE IF NOT EXISTS` no _SCHEMA nao alcanca
    # bancos antigos, entao entram aqui via ALTER TABLE, uma por vez, por tabela.
    _COLUNAS_NOVAS_POR_TABELA = {
        "prestadores": [
            ("ativo", "INTEGER NOT NULL DEFAULT 1"),
        ],
        "notas": [
            ("cod_motivo_cancelamento", "TEXT"),
            ("motivo_cancelamento_texto", "TEXT"),
            ("erro_cancelamento", "TEXT"),
            ("protocolo_cancelamento", "TEXT"),
            ("cancelamento_confirmado_em", "TEXT"),
            ("email_tentativas", "INTEGER NOT NULL DEFAULT 0"),
            ("proxima_tentativa_email_em", "TEXT"),
            ("retem_irrf", "INTEGER NOT NULL DEFAULT 0"),
            ("aliquota_irrf", "TEXT"),
            ("retem_pis", "INTEGER NOT NULL DEFAULT 0"),
            ("aliquota_pis", "TEXT"),
            ("retem_cofins", "INTEGER NOT NULL DEFAULT 0"),
            ("aliquota_cofins", "TEXT"),
            ("retem_csll", "INTEGER NOT NULL DEFAULT 0"),
            ("aliquota_csll", "TEXT"),
            ("retem_inss", "INTEGER NOT NULL DEFAULT 0"),
            ("aliquota_inss", "TEXT"),
            ("retem_iss", "INTEGER NOT NULL DEFAULT 0"),
        ],
        "tomadores": [
            ("retem_irrf", "INTEGER NOT NULL DEFAULT 0"),
            ("aliquota_irrf", "TEXT"),
            ("retem_pis", "INTEGER NOT NULL DEFAULT 0"),
            ("aliquota_pis", "TEXT"),
            ("retem_cofins", "INTEGER NOT NULL DEFAULT 0"),
            ("aliquota_cofins", "TEXT"),
            ("retem_csll", "INTEGER NOT NULL DEFAULT 0"),
            ("aliquota_csll", "TEXT"),
            ("retem_inss", "INTEGER NOT NULL DEFAULT 0"),
            ("aliquota_inss", "TEXT"),
            ("retem_iss", "INTEGER NOT NULL DEFAULT 0"),
            ("ativo", "INTEGER NOT NULL DEFAULT 1"),
        ],
        "modelos_servico": [
            ("precisa_revisao_cod_trib_municipal", "INTEGER NOT NULL DEFAULT 0"),
        ],
    }

    def _migrar(self) -> None:
        self._conn.executescript(_SCHEMA)
        for tabela, colunas_novas in self._COLUNAS_NOVAS_POR_TABELA.items():
            colunas_existentes = {
                linha["name"] for linha in self._conn.execute(f"PRAGMA table_info({tabela})").fetchall()
            }
            for nome, tipo in colunas_novas:
                if nome not in colunas_existentes:
                    self._conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")
        # Bancos de clientes reais ja tinham modelos de servico com
        # cod_tributacao_municipal de 10 digitos (formato antigo, invalido
        # pro XSD oficial -- docs/auditoria-2.md, secao 8.1). Nao apaga nem
        # reescreve o valor cadastrado (pode ser dado real da prefeitura que
        # so' por coincidencia tem outro tamanho) -- so marca pra revisao
        # obrigatoria; `_precisa_revisao_cod_trib_municipal` recalcula isso
        # de novo a cada criar/atualizar, entao um valor ja corrigido nunca
        # fica preso com a marca. Roda toda vez (idempotente) como rede de
        # seguranca, nao so' na migracao da coluna nova.
        self._conn.execute(
            "UPDATE modelos_servico SET precisa_revisao_cod_trib_municipal = 1 "
            "WHERE cod_tributacao_municipal != '' AND cod_tributacao_municipal "
            "NOT GLOB '[0-9][0-9][0-9]'"
        )
        self._conn.commit()

    def fechar(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Repositorio":
        return self

    def __exit__(self, *_exc) -> None:
        self.fechar()

    # ------------------------------------------------------------------
    # prestadores
    # ------------------------------------------------------------------

    def criar_prestador(
        self,
        *,
        nome_exibicao: str,
        cnpj: str,
        im: str,
        codigo_municipio: str,
        regime: str = "1",
        regime_especial_tributacao: str = "0",
        caminho_pfx: Optional[str] = None,
        cor: Optional[str] = None,
        pasta_nome: Optional[str] = None,
        cert_venc_em: Optional[str] = None,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO prestadores
               (nome_exibicao, cnpj, im, codigo_municipio, regime,
                regime_especial_tributacao, caminho_pfx, cor, pasta_nome, cert_venc_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                nome_exibicao, cnpj, im, codigo_municipio, regime,
                regime_especial_tributacao, caminho_pfx, cor, pasta_nome, cert_venc_em,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def obter_prestador(self, prestador_id: int) -> Optional[Dict[str, Any]]:
        linha = self._conn.execute(
            "SELECT * FROM prestadores WHERE id = ?", (prestador_id,)
        ).fetchone()
        return _linha_para_dict(linha)

    def listar_prestadores(self, *, apenas_ativos: bool = True) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM prestadores"
        if apenas_ativos:
            sql += " WHERE ativo = 1"
        sql += " ORDER BY nome_exibicao"
        linhas = self._conn.execute(sql).fetchall()
        return [dict(l) for l in linhas]

    def atualizar_prestador(
        self, prestador_id: int, *, nome_exibicao: str, im: str, codigo_municipio: str,
        regime: str, regime_especial_tributacao: str, cor: Optional[str] = None,
        pasta_nome: Optional[str] = None,
    ) -> None:
        """Edita os dados de cadastro do prestador. CNPJ e certificado (.pfx)
        não mudam por aqui — trocar de CNPJ seria virar outro prestador, e
        trocar de certificado tem fluxo próprio (onboarding).

        `pasta_nome`: só passar quando a pasta física já tiver sido renomeada
        de verdade (ver `app.core.pastas.renomear_pasta_prestador`,
        docs/auditoria.md Bloco 4.2) -- `None` (padrão) preserva o valor
        atual via COALESCE, nunca apaga um `pasta_nome` já travado sem
        querer só por editar outro campo do cadastro."""
        self._conn.execute(
            """UPDATE prestadores SET nome_exibicao = ?, im = ?, codigo_municipio = ?,
               regime = ?, regime_especial_tributacao = ?, cor = ?,
               pasta_nome = COALESCE(?, pasta_nome)
               WHERE id = ?""",
            (nome_exibicao, im, codigo_municipio, regime, regime_especial_tributacao, cor, pasta_nome, prestador_id),
        )
        self._conn.commit()

    def excluir_prestador(self, prestador_id: int) -> None:
        """Remove o prestador e seus cadastros filhos (tomadores, modelos,
        mensalidades). Bloqueia se existir QUALQUER nota emitida para ele —
        um documento fiscal não pode ficar sem o prestador que o emitiu.
        Pra esse caso, use `inativar_prestador` (docs/auditoria.md, Bloco
        4.1): tira da lista ativa sem apagar nada."""
        if self._conn.execute(
            "SELECT 1 FROM notas WHERE prestador_id = ? LIMIT 1", (prestador_id,)
        ).fetchone():
            raise ValueError(
                "Este prestador tem notas emitidas — não é possível excluir. Você pode inativá-lo."
            )
        self._conn.execute("DELETE FROM recorrencias WHERE prestador_id = ?", (prestador_id,))
        self._conn.execute("DELETE FROM modelos_servico WHERE prestador_id = ?", (prestador_id,))
        self._conn.execute("DELETE FROM tomadores WHERE prestador_id = ?", (prestador_id,))
        self._conn.execute("DELETE FROM prestadores WHERE id = ?", (prestador_id,))
        self._conn.commit()

    def inativar_prestador(self, prestador_id: int) -> None:
        """Tira o prestador da lista ativa sem apagar NADA (docs/auditoria.md,
        Bloco 4.1) -- notas, arquivos e cadastros filhos continuam intactos.
        Pausa também as mensalidades ativas dele (não faz sentido continuar
        cobrando um prestador que o usuário acabou de inativar)."""
        self._conn.execute("UPDATE prestadores SET ativo = 0 WHERE id = ?", (prestador_id,))
        self._conn.execute(
            "UPDATE recorrencias SET ativo = 0 WHERE prestador_id = ? AND ativo = 1", (prestador_id,)
        )
        self._conn.commit()

    def reativar_prestador(self, prestador_id: int) -> None:
        self._conn.execute("UPDATE prestadores SET ativo = 1 WHERE id = ?", (prestador_id,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # tomadores (sempre filtrado por prestador_id)
    # ------------------------------------------------------------------

    def criar_tomador(
        self, prestador_id: int, *, doc: str, nome: str,
        email: Optional[str] = None, telefone: Optional[str] = None, endereco: Optional[str] = None,
        retencoes: Optional[Dict[str, Any]] = None,
    ) -> int:
        r = _normalizar_retencoes(retencoes)
        colunas = ", ".join(CAMPOS_RETENCAO)
        interrogacoes = ", ".join("?" * len(CAMPOS_RETENCAO))
        cur = self._conn.execute(
            f"""INSERT INTO tomadores (prestador_id, doc, nome, email, telefone, endereco, {colunas})
               VALUES (?, ?, ?, ?, ?, ?, {interrogacoes})""",
            (prestador_id, doc, nome, email, telefone, endereco, *(r[c] for c in CAMPOS_RETENCAO)),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def obter_tomador(self, prestador_id: int, tomador_id: int) -> Optional[Dict[str, Any]]:
        linha = self._conn.execute(
            "SELECT * FROM tomadores WHERE prestador_id = ? AND id = ?",
            (prestador_id, tomador_id),
        ).fetchone()
        return _linha_para_dict(linha)

    def listar_tomadores(self, prestador_id: int, *, apenas_ativos: bool = True) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM tomadores WHERE prestador_id = ?"
        params: List[Any] = [prestador_id]
        if apenas_ativos:
            sql += " AND ativo = 1"
        sql += " ORDER BY nome"
        linhas = self._conn.execute(sql, params).fetchall()
        return [dict(l) for l in linhas]

    def tomadores_com_nome_duplicado(self, prestador_id: int, nome: str) -> List[Dict[str, Any]]:
        """Usado para decidir o sufixo de CNPJ curto no nome de arquivo (espec, §5b)."""
        linhas = self._conn.execute(
            "SELECT * FROM tomadores WHERE prestador_id = ? AND nome = ?",
            (prestador_id, nome),
        ).fetchall()
        return [dict(l) for l in linhas]

    def atualizar_tomador(
        self, prestador_id: int, tomador_id: int, *, nome: str,
        email: Optional[str] = None, telefone: Optional[str] = None, endereco: Optional[str] = None,
        retencoes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Edita os dados do tomador. O documento (CNPJ/CPF) não muda por
        aqui — é a chave que identifica o tomador nas notas já emitidas."""
        r = _normalizar_retencoes(retencoes)
        atribuicoes = ", ".join(f"{c} = ?" for c in CAMPOS_RETENCAO)
        self._conn.execute(
            f"""UPDATE tomadores SET nome = ?, email = ?, telefone = ?, endereco = ?, {atribuicoes}
               WHERE prestador_id = ? AND id = ?""",
            (nome, email, telefone, endereco, *(r[c] for c in CAMPOS_RETENCAO), prestador_id, tomador_id),
        )
        self._conn.commit()

    def excluir_tomador(self, prestador_id: int, tomador_id: int) -> None:
        """Bloqueia se o tomador tiver nota emitida ou mensalidade cadastrada
        — nesse caso a orientação é usar `inativar_tomador` (docs/auditoria.md,
        Bloco 4.1): tira da lista ativa sem apagar nada."""
        if self._conn.execute(
            "SELECT 1 FROM notas WHERE prestador_id = ? AND tomador_id = ? LIMIT 1",
            (prestador_id, tomador_id),
        ).fetchone():
            raise ValueError("Este tomador tem notas emitidas — não é possível excluir. Você pode inativá-lo.")
        if self._conn.execute(
            "SELECT 1 FROM recorrencias WHERE prestador_id = ? AND tomador_id = ? LIMIT 1",
            (prestador_id, tomador_id),
        ).fetchone():
            raise ValueError(
                "Este tomador tem uma mensalidade cadastrada — exclua a mensalidade antes, ou inative o tomador."
            )
        self._conn.execute(
            "DELETE FROM tomadores WHERE prestador_id = ? AND id = ?", (prestador_id, tomador_id)
        )
        self._conn.commit()

    def inativar_tomador(self, prestador_id: int, tomador_id: int) -> None:
        """Tira o tomador da lista ativa sem apagar NADA (docs/auditoria.md,
        Bloco 4.1) -- histórico de notas continua intacto. Pausa também
        mensalidades ativas dele (não faz sentido continuar cobrando um
        tomador que acabou de ser inativado)."""
        self._conn.execute(
            "UPDATE tomadores SET ativo = 0 WHERE prestador_id = ? AND id = ?", (prestador_id, tomador_id)
        )
        self._conn.execute(
            "UPDATE recorrencias SET ativo = 0 WHERE prestador_id = ? AND tomador_id = ? AND ativo = 1",
            (prestador_id, tomador_id),
        )
        self._conn.commit()

    def reativar_tomador(self, prestador_id: int, tomador_id: int) -> None:
        self._conn.execute(
            "UPDATE tomadores SET ativo = 1 WHERE prestador_id = ? AND id = ?", (prestador_id, tomador_id)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # modelos_servico
    # ------------------------------------------------------------------

    def criar_modelo_servico(
        self, prestador_id: int, *, descricao: str, cod_tributacao_nacional: str,
        cod_tributacao_municipal: str, cod_nbs: str, valor_padrao: str,
        aliquota: Optional[str] = None,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO modelos_servico
               (prestador_id, descricao, cod_tributacao_nacional, cod_tributacao_municipal,
                cod_nbs, valor_padrao, aliquota, precisa_revisao_cod_trib_municipal)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (prestador_id, descricao, cod_tributacao_nacional, cod_tributacao_municipal,
             cod_nbs, valor_padrao, aliquota,
             int(_precisa_revisao_cod_trib_municipal(cod_tributacao_municipal))),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def obter_modelo(self, prestador_id: int, modelo_id: int) -> Optional[Dict[str, Any]]:
        linha = self._conn.execute(
            "SELECT * FROM modelos_servico WHERE prestador_id = ? AND id = ?",
            (prestador_id, modelo_id),
        ).fetchone()
        return _linha_para_dict(linha)

    def listar_modelos_servico(self, prestador_id: int) -> List[Dict[str, Any]]:
        linhas = self._conn.execute(
            "SELECT * FROM modelos_servico WHERE prestador_id = ? ORDER BY descricao",
            (prestador_id,),
        ).fetchall()
        return [dict(l) for l in linhas]

    def atualizar_modelo_servico(
        self, prestador_id: int, modelo_id: int, *, descricao: str, cod_tributacao_nacional: str,
        cod_tributacao_municipal: str, cod_nbs: str, valor_padrao: str, aliquota: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            """UPDATE modelos_servico SET descricao = ?, cod_tributacao_nacional = ?,
               cod_tributacao_municipal = ?, cod_nbs = ?, valor_padrao = ?, aliquota = ?,
               precisa_revisao_cod_trib_municipal = ?
               WHERE prestador_id = ? AND id = ?""",
            (descricao, cod_tributacao_nacional, cod_tributacao_municipal, cod_nbs,
             valor_padrao, aliquota, int(_precisa_revisao_cod_trib_municipal(cod_tributacao_municipal)),
             prestador_id, modelo_id),
        )
        self._conn.commit()

    def excluir_modelo_servico(self, prestador_id: int, modelo_id: int) -> None:
        """Bloqueia se o modelo tiver nota emitida ou mensalidade em uso."""
        if self._conn.execute(
            "SELECT 1 FROM notas WHERE prestador_id = ? AND modelo_id = ? LIMIT 1",
            (prestador_id, modelo_id),
        ).fetchone():
            raise ValueError("Este serviço tem notas emitidas — não é possível excluir.")
        if self._conn.execute(
            "SELECT 1 FROM recorrencias WHERE prestador_id = ? AND modelo_id = ? LIMIT 1",
            (prestador_id, modelo_id),
        ).fetchone():
            raise ValueError("Este serviço está em uso numa mensalidade — exclua ou pause a mensalidade antes.")
        self._conn.execute(
            "DELETE FROM modelos_servico WHERE prestador_id = ? AND id = ?", (prestador_id, modelo_id)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # recorrencias
    # ------------------------------------------------------------------

    def criar_recorrencia(
        self, prestador_id: int, *, tomador_id: int, modelo_id: int, valor: str,
        dia_do_mes: int, ativo: bool = True,
    ) -> int:
        _exigir_dia_do_mes_valido(dia_do_mes)
        cur = self._conn.execute(
            """INSERT INTO recorrencias (prestador_id, tomador_id, modelo_id, valor, dia_do_mes, ativo)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (prestador_id, tomador_id, modelo_id, valor, dia_do_mes, int(ativo)),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def listar_recorrencias(self, prestador_id: int, apenas_ativas: bool = True) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM recorrencias WHERE prestador_id = ?"
        params: List[Any] = [prestador_id]
        if apenas_ativas:
            sql += " AND ativo = 1"
        linhas = self._conn.execute(sql, params).fetchall()
        return [dict(l) for l in linhas]

    def atualizar_recorrencia_ativo(self, prestador_id: int, recorrencia_id: int, ativo: bool) -> None:
        """Pausar/reativar uma mensalidade (botão liga/desliga do Meu Dia/API)."""
        self._conn.execute(
            "UPDATE recorrencias SET ativo = ? WHERE prestador_id = ? AND id = ?",
            (int(ativo), prestador_id, recorrencia_id),
        )
        self._conn.commit()

    def atualizar_recorrencia(
        self, prestador_id: int, recorrencia_id: int, *,
        tomador_id: int, modelo_id: int, valor: str, dia_do_mes: int,
    ) -> None:
        _exigir_dia_do_mes_valido(dia_do_mes)
        self._conn.execute(
            """UPDATE recorrencias SET tomador_id = ?, modelo_id = ?, valor = ?, dia_do_mes = ?
               WHERE prestador_id = ? AND id = ?""",
            (tomador_id, modelo_id, valor, dia_do_mes, prestador_id, recorrencia_id),
        )
        self._conn.commit()

    def excluir_recorrencia(self, prestador_id: int, recorrencia_id: int) -> None:
        """Bloqueia se já existir nota originada desta mensalidade — preserva
        o vínculo histórico que aparece no Histórico. Pra parar de cobrar sem
        perder o histórico, use `atualizar_recorrencia_ativo` (pausar)."""
        if self._conn.execute(
            "SELECT 1 FROM notas WHERE prestador_id = ? AND recorrencia_id = ? LIMIT 1",
            (prestador_id, recorrencia_id),
        ).fetchone():
            raise ValueError("Esta mensalidade já tem nota emitida — pause em vez de excluir.")
        self._conn.execute(
            "DELETE FROM recorrencias WHERE prestador_id = ? AND id = ?", (prestador_id, recorrencia_id)
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # notas
    # ------------------------------------------------------------------

    def _proximo_numero_dps(self, prestador_id: int, serie: str) -> str:
        linha = self._conn.execute(
            "SELECT COALESCE(MAX(CAST(numero_dps AS INTEGER)), 0) AS maior "
            "FROM notas WHERE prestador_id = ? AND serie = ?",
            (prestador_id, serie),
        ).fetchone()
        return str(int(linha["maior"]) + 1)

    def criar_nota(
        self, prestador_id: int, *, tomador_id: int, modelo_id: int, valor: str,
        serie: str = "1", numero_dps: Optional[str] = None, recorrencia_id: Optional[int] = None,
        retencoes: Optional[Dict[str, Any]] = None,
    ) -> int:
        """`retencoes`: se None, a nota nasce sem nenhuma retencao (nao
        retido em tudo) — quem chama (app/api.py, app/core/fila.py) decide se
        usa o padrao do tomador ou um valor sobrescrito so' pra esta nota
        (docs/auditoria.md, Bloco 1.6/2.4, item "permitir sobrescrever so'
        naquela nota").

        Numeracao (docs/auditoria.md, Bloco 4.7 / Bloco 6, item "numeracao
        sem furo e sem repeticao"): `numero_dps` e' sempre MAX+1 por
        prestador+serie quando nao informado explicitamente. A constraint
        UNIQUE(prestador_id, serie, numero_dps) ja IMPEDIA duplicata mesmo
        antes desta funcao existir (2 emissoes quase simultaneas nunca
        conseguiam gravar o mesmo numero) -- o que faltava era nao quebrar
        com um erro tecnico cru nessa colisao rara: agora ela recalcula o
        proximo numero e tenta de novo, algumas vezes, antes de desistir."""
        r = _normalizar_retencoes(retencoes)
        colunas = ", ".join(CAMPOS_RETENCAO)
        interrogacoes = ", ".join("?" * len(CAMPOS_RETENCAO))
        numero_explicito = numero_dps is not None
        tentativas_restantes = 1 if numero_explicito else 5
        while True:
            numero_da_vez = numero_dps if numero_explicito else self._proximo_numero_dps(prestador_id, serie)
            try:
                cur = self._conn.execute(
                    f"""INSERT INTO notas
                       (prestador_id, tomador_id, modelo_id, recorrencia_id, valor, serie, numero_dps, status, {colunas})
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, {interrogacoes})""",
                    (
                        prestador_id, tomador_id, modelo_id, recorrencia_id, valor, serie, numero_da_vez,
                        STATUS_PENDENTE, *(r[c] for c in CAMPOS_RETENCAO),
                    ),
                )
            except sqlite3.IntegrityError:
                tentativas_restantes -= 1
                if tentativas_restantes <= 0:
                    raise
                continue
            self._conn.commit()
            return int(cur.lastrowid)

    def obter_nota(self, prestador_id: int, nota_id: int) -> Optional[Dict[str, Any]]:
        linha = self._conn.execute(
            "SELECT * FROM notas WHERE prestador_id = ? AND id = ?", (prestador_id, nota_id)
        ).fetchone()
        return _linha_para_dict(linha)

    def listar_notas(self, prestador_id: int, status: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM notas WHERE prestador_id = ?"
        params: List[Any] = [prestador_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY id"
        linhas = self._conn.execute(sql, params).fetchall()
        return [dict(l) for l in linhas]

    def listar_notas_detalhado(self, prestador_id: int, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Como `listar_notas`, mas ja traz o nome/telefone do tomador —
        usado pelo Historico pra nao precisar de N+1 chamadas."""
        sql = (
            "SELECT n.*, t.nome AS tomador_nome, t.telefone AS tomador_telefone, t.email AS tomador_email "
            "FROM notas n JOIN tomadores t ON t.id = n.tomador_id "
            "WHERE n.prestador_id = ?"
        )
        params: List[Any] = [prestador_id]
        if status is not None:
            sql += " AND n.status = ?"
            params.append(status)
        sql += " ORDER BY n.id DESC"
        linhas = self._conn.execute(sql, params).fetchall()
        return [dict(l) for l in linhas]

    def incrementar_tentativa(self, prestador_id: int, nota_id: int) -> None:
        self._conn.execute(
            "UPDATE notas SET tentativas = tentativas + 1 WHERE prestador_id = ? AND id = ?",
            (prestador_id, nota_id),
        )
        self._conn.commit()

    def marcar_emitida(
        self, prestador_id: int, nota_id: int, *, chave_acesso: str, xml_conteudo: str,
        xml_path: Optional[str] = None, pdf_path: Optional[str] = None,
        emitida_em: Optional[dt.datetime] = None,
    ) -> None:
        self._conn.execute(
            """UPDATE notas SET status = ?, chave_acesso = ?, xml_conteudo = ?, xml_path = ?,
               pdf_path = ?, motivo_rejeicao = NULL, proxima_tentativa_em = NULL, emitida_em = ?
               WHERE prestador_id = ? AND id = ?""",
            (
                STATUS_EMITIDA, chave_acesso, xml_conteudo, xml_path, pdf_path,
                _iso(emitida_em) or dt.datetime.now().isoformat(sep=" "),
                prestador_id, nota_id,
            ),
        )
        self._conn.commit()

    def marcar_rejeitada(self, prestador_id: int, nota_id: int, *, motivo: str) -> None:
        self._conn.execute(
            """UPDATE notas SET status = ?, motivo_rejeicao = ?, proxima_tentativa_em = NULL
               WHERE prestador_id = ? AND id = ?""",
            (STATUS_REJEITADA, motivo, prestador_id, nota_id),
        )
        self._conn.commit()

    def marcar_para_retry(self, prestador_id: int, nota_id: int, *, proxima_tentativa_em: dt.datetime) -> None:
        self._conn.execute(
            """UPDATE notas SET status = ?, proxima_tentativa_em = ?
               WHERE prestador_id = ? AND id = ?""",
            (STATUS_PENDENTE, _iso(proxima_tentativa_em), prestador_id, nota_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # cancelamento (evento e101101 — docs/auditoria.md, Bloco 4.4)
    #
    # Nunca existe um "marcar_cancelada" direto: o unico caminho pra
    # STATUS_CANCELADA e' `marcar_cancelamento_confirmado`, chamado so' depois
    # de uma resposta de sucesso real do governo (fila.processar_cancelamentos).
    # ------------------------------------------------------------------

    def iniciar_cancelamento(
        self, prestador_id: int, nota_id: int, *, cod_motivo: str, motivo_texto: Optional[str] = None,
    ) -> None:
        """Marca a intencao de cancelar. So' aceita notas EMITIDAS — bloqueia
        de propria mao (sem precisar de rede) cancelar de novo uma nota ja
        cancelada, ou uma pendente/rejeitada que nunca chegou a ser emitida."""
        nota = self.obter_nota(prestador_id, nota_id)
        if nota is None:
            raise ValueError("Nota nao encontrada.")
        if nota["status"] != STATUS_EMITIDA:
            if nota["status"] == STATUS_CANCELADA:
                raise ValueError("Esta nota ja foi cancelada — nao e' possivel cancelar de novo.")
            if nota["status"] == STATUS_CANCELAMENTO_PENDENTE:
                raise ValueError("Ja existe um cancelamento em andamento pra esta nota.")
            raise ValueError("So' e' possivel cancelar uma nota que foi emitida com sucesso.")
        self._conn.execute(
            """UPDATE notas SET status = ?, cod_motivo_cancelamento = ?, motivo_cancelamento_texto = ?,
               erro_cancelamento = NULL, tentativas = 0, proxima_tentativa_em = NULL
               WHERE prestador_id = ? AND id = ?""",
            (STATUS_CANCELAMENTO_PENDENTE, cod_motivo, motivo_texto, prestador_id, nota_id),
        )
        self._conn.commit()

    def marcar_cancelamento_confirmado(
        self, prestador_id: int, nota_id: int, *,
        protocolo: str, confirmado_em: str, xml_path: Optional[str], pdf_path: Optional[str],
    ) -> None:
        """Unico lugar do codigo que grava STATUS_CANCELADA — so' chamado
        depois que o governo confirmou o evento de cancelamento de verdade."""
        self._conn.execute(
            """UPDATE notas SET status = ?, xml_path = ?, pdf_path = ?,
               protocolo_cancelamento = ?, cancelamento_confirmado_em = ?
               WHERE prestador_id = ? AND id = ?""",
            (STATUS_CANCELADA, xml_path, pdf_path, protocolo, confirmado_em, prestador_id, nota_id),
        )
        self._conn.commit()

    def agendar_retry_cancelamento(
        self, prestador_id: int, nota_id: int, *, proxima_tentativa_em: dt.datetime
    ) -> None:
        """Sem internet / erro de rede ao tentar cancelar: continua
        CANCELAMENTO_PENDENTE (nunca 'cancelada'), agenda nova tentativa."""
        self._conn.execute(
            """UPDATE notas SET status = ?, proxima_tentativa_em = ?
               WHERE prestador_id = ? AND id = ?""",
            (STATUS_CANCELAMENTO_PENDENTE, _iso(proxima_tentativa_em), prestador_id, nota_id),
        )
        self._conn.commit()

    def reverter_cancelamento(self, prestador_id: int, nota_id: int, *, motivo_falha: str) -> None:
        """O governo RECUSOU o cancelamento (fora do prazo, ja tem evento
        vinculado etc.) — a nota continua valida, volta pra EMITIDA (nunca
        fica presa em CANCELAMENTO_PENDENTE pra sempre), guarda o motivo
        pra tela mostrar uma mensagem clara."""
        self._conn.execute(
            """UPDATE notas SET status = ?, erro_cancelamento = ?, proxima_tentativa_em = NULL
               WHERE prestador_id = ? AND id = ?""",
            (STATUS_EMITIDA, motivo_falha, prestador_id, nota_id),
        )
        self._conn.commit()

    def listar_cancelamentos_pendentes_prontos_para_tentar(
        self, agora: dt.datetime
    ) -> List[Dict[str, Any]]:
        """Mesma excecao deliberada de escopo que `listar_notas_pendentes_prontas_para_tentar`
        (ver docstring la em cima) — o agendador varre todos os prestadores."""
        linhas = self._conn.execute(
            """SELECT * FROM notas
               WHERE status = ?
                 AND (proxima_tentativa_em IS NULL OR proxima_tentativa_em <= ?)
               ORDER BY id""",
            (STATUS_CANCELAMENTO_PENDENTE, _iso(agora)),
        ).fetchall()
        return [dict(l) for l in linhas]

    def marcar_email_enviado(self, prestador_id: int, nota_id: int) -> None:
        self._conn.execute(
            """UPDATE notas SET email_status = ?, email_erro = NULL,
               email_tentativas = 0, proxima_tentativa_email_em = NULL
               WHERE prestador_id = ? AND id = ?""",
            (EMAIL_ENVIADO, prestador_id, nota_id),
        )
        self._conn.commit()

    def marcar_email_falhou(
        self, prestador_id: int, nota_id: int, *, erro: str,
        proxima_tentativa_em: Optional[dt.datetime] = None,
    ) -> None:
        """`proxima_tentativa_em`: agenda o retry automatico (core/email.
        reprocessar_emails_falhados, chamado pelo agendador a cada ciclo) --
        mesmo backoff da fila de emissao (app.core.backoff), calculado por
        quem chama (core/email.enviar_nota_email) com base em
        notas.email_tentativas. Mesmo caminho pro clique manual "Reenviar"
        do Historico e pro retry automatico -- igual a fila de emissao, que
        tambem nao distingue disparo manual de automatico pra agendar retry."""
        self._conn.execute(
            """UPDATE notas SET email_status = ?, email_erro = ?,
               email_tentativas = email_tentativas + 1, proxima_tentativa_email_em = ?
               WHERE prestador_id = ? AND id = ?""",
            (EMAIL_FALHOU, erro, _iso(proxima_tentativa_em), prestador_id, nota_id),
        )
        self._conn.commit()

    def listar_notas_email_falhou_prontas_para_tentar(self, agora: dt.datetime) -> List[Dict[str, Any]]:
        """Mesma excecao deliberada de escopo que `listar_notas_pendentes_prontas_para_tentar`
        (ver docstring la em cima) -- o agendador varre todos os prestadores."""
        linhas = self._conn.execute(
            """SELECT * FROM notas
               WHERE email_status = ?
                 AND (proxima_tentativa_email_em IS NULL OR proxima_tentativa_email_em <= ?)
               ORDER BY id""",
            (EMAIL_FALHOU, _iso(agora)),
        ).fetchall()
        return [dict(l) for l in linhas]

    def historico_valores_tomador(
        self, prestador_id: int, tomador_id: int, modelo_id: int, *, limite: int = 6
    ) -> List[str]:
        """Ultimos `limite` valores de notas EMITIDAS com sucesso pro mesmo
        tomador+servico, mais recente primeiro -- base pro alerta de "valor
        fora do padrao" (app.core.valores.valor_foge_do_padrao) antes de
        emitir uma nota avulsa."""
        linhas = self._conn.execute(
            """SELECT valor FROM notas
               WHERE prestador_id = ? AND tomador_id = ? AND modelo_id = ? AND status = ?
               ORDER BY id DESC LIMIT ?""",
            (prestador_id, tomador_id, modelo_id, STATUS_EMITIDA, limite),
        ).fetchall()
        return [l["valor"] for l in linhas]

    def listar_notas_do_mes(self, prestador_id: int, ano: int, mes: int) -> List[Dict[str, Any]]:
        """Notas emitidas/canceladas num mes especifico — usado pelo
        'Fechar mes' (Etapa 3 item 6, espec §2 item 9b)."""
        sql = (
            "SELECT n.*, t.nome AS tomador_nome "
            "FROM notas n JOIN tomadores t ON t.id = n.tomador_id "
            "WHERE n.prestador_id = ? AND n.status IN (?, ?) "
            "AND strftime('%Y-%m', COALESCE(n.emitida_em, n.criada_em)) = ? "
            "ORDER BY n.numero_dps"
        )
        mes_ref = f"{ano:04d}-{mes:02d}"
        linhas = self._conn.execute(
            sql, (prestador_id, STATUS_EMITIDA, STATUS_CANCELADA, mes_ref)
        ).fetchall()
        return [dict(l) for l in linhas]

    def listar_notas_pendentes_prontas_para_tentar(
        self, agora: dt.datetime
    ) -> List[Dict[str, Any]]:
        """Excecao deliberada ao escopo por prestador_id: a fila (core/fila.py)
        precisa varrer TODOS os prestadores a cada ciclo do agendador, igual ao
        painel "Meu Dia" da espec — leitura agregada, sem SQL fora deste arquivo."""
        linhas = self._conn.execute(
            """SELECT * FROM notas
               WHERE status = ?
                 AND (proxima_tentativa_em IS NULL OR proxima_tentativa_em <= ?)
               ORDER BY id""",
            (STATUS_PENDENTE, _iso(agora)),
        ).fetchall()
        return [dict(l) for l in linhas]

    # ------------------------------------------------------------------
    # painel "Meu Dia" (espec, secao 2 item 1b) — excecao deliberada de
    # escopo, ver docstring do modulo. So leitura, agregando TODOS os
    # prestadores; nenhuma escrita acontece aqui.
    # ------------------------------------------------------------------

    def dados_meu_dia(self, hoje: dt.date, dias_alerta_certificado: int = 30) -> Dict[str, List[Dict[str, Any]]]:
        mensalidades_hoje = self._conn.execute(
            """SELECT r.id, r.prestador_id, p.nome_exibicao AS prestador_nome, p.cor AS prestador_cor,
                      r.tomador_id, t.nome AS tomador_nome, r.modelo_id, m.descricao AS modelo_descricao,
                      r.valor,
                      EXISTS(
                          SELECT 1 FROM notas n
                          WHERE n.recorrencia_id = r.id
                            AND strftime('%Y-%m', n.criada_em) = strftime('%Y-%m', ?)
                            AND n.status != ?
                      ) AS ja_emitida_no_mes
               FROM recorrencias r
               JOIN prestadores p ON p.id = r.prestador_id
               JOIN tomadores t ON t.id = r.tomador_id
               JOIN modelos_servico m ON m.id = r.modelo_id
               WHERE r.ativo = 1 AND r.dia_do_mes = ?
               ORDER BY p.nome_exibicao, t.nome""",
            (hoje.isoformat(), STATUS_CANCELADA, hoje.day),
        ).fetchall()

        notas_pendentes = self._conn.execute(
            """SELECT n.id, n.prestador_id, p.nome_exibicao AS prestador_nome, p.cor AS prestador_cor,
                      n.tomador_id, t.nome AS tomador_nome, n.valor, n.tentativas,
                      n.proxima_tentativa_em, n.criada_em
               FROM notas n
               JOIN prestadores p ON p.id = n.prestador_id
               JOIN tomadores t ON t.id = n.tomador_id
               WHERE n.status = ?
               ORDER BY n.criada_em""",
            (STATUS_PENDENTE,),
        ).fetchall()

        notas_rejeitadas = self._conn.execute(
            """SELECT n.id, n.prestador_id, p.nome_exibicao AS prestador_nome, p.cor AS prestador_cor,
                      n.tomador_id, t.nome AS tomador_nome, n.valor, n.motivo_rejeicao, n.criada_em
               FROM notas n
               JOIN prestadores p ON p.id = n.prestador_id
               JOIN tomadores t ON t.id = n.tomador_id
               WHERE n.status = ?
               ORDER BY n.criada_em DESC""",
            (STATUS_REJEITADA,),
        ).fetchall()

        certificados_a_vencer = self._conn.execute(
            """SELECT id AS prestador_id, nome_exibicao AS prestador_nome, cor AS prestador_cor,
                      cert_venc_em, CAST(julianday(cert_venc_em) - julianday(?) AS INTEGER) AS dias_restantes
               FROM prestadores
               WHERE cert_venc_em IS NOT NULL
                 AND julianday(cert_venc_em) - julianday(?) <= ?
               ORDER BY cert_venc_em""",
            (hoje.isoformat(), hoje.isoformat(), dias_alerta_certificado),
        ).fetchall()

        return {
            "mensalidades_hoje": [dict(l) for l in mensalidades_hoje],
            "notas_pendentes": [dict(l) for l in notas_pendentes],
            "notas_rejeitadas": [dict(l) for l in notas_rejeitadas],
            "certificados_a_vencer": [dict(l) for l in certificados_a_vencer],
            "sugestoes_mensalidade": self.sugestoes_de_mensalidade(hoje),
        }

    def sugestoes_de_mensalidade(self, hoje: dt.date, meses_seguidos: int = 2) -> List[Dict[str, Any]]:
        """Item 4 da automacao pedida: detecta tomador+servico emitidos NA
        MAO (recorrencia_id IS NULL) em cada um dos ultimos `meses_seguidos`
        meses de calendario (incluindo o mes atual) e sugere virar
        mensalidade -- converte trabalho manual repetido em zero-clique sem
        a secretaria ter que lembrar de configurar sozinha.

        So' sugere se AINDA nao existe recorrencia ativa pra esse mesmo
        tomador+servico (senao ficaria sugerindo algo que ja foi feito).
        E' so' leitura + calculo em Python — nenhuma escrita, e' a mesma
        excecao deliberada de escopo global do resto deste metodo (ver
        docstring do modulo)."""
        linhas = self._conn.execute(
            """SELECT n.prestador_id, p.nome_exibicao AS prestador_nome, p.cor AS prestador_cor,
                      n.tomador_id, t.nome AS tomador_nome, n.modelo_id, m.descricao AS modelo_descricao,
                      n.valor, strftime('%Y-%m', COALESCE(n.emitida_em, n.criada_em)) AS mes_ref
               FROM notas n
               JOIN prestadores p ON p.id = n.prestador_id
               JOIN tomadores t ON t.id = n.tomador_id
               JOIN modelos_servico m ON m.id = n.modelo_id
               WHERE n.status = ? AND n.recorrencia_id IS NULL AND p.ativo = 1 AND t.ativo = 1
               ORDER BY n.prestador_id, n.tomador_id, n.modelo_id, n.id DESC""",
            (STATUS_EMITIDA,),
        ).fetchall()

        meses_esperados = set()
        ano, mes = hoje.year, hoje.month
        for _ in range(meses_seguidos):
            meses_esperados.add(f"{ano:04d}-{mes:02d}")
            mes -= 1
            if mes == 0:
                mes, ano = 12, ano - 1

        grupos: Dict[tuple, List[sqlite3.Row]] = defaultdict(list)
        for linha in linhas:
            grupos[(linha["prestador_id"], linha["tomador_id"], linha["modelo_id"])].append(linha)

        ja_tem_recorrencia = {
            (l["prestador_id"], l["tomador_id"], l["modelo_id"])
            for l in self._conn.execute(
                "SELECT prestador_id, tomador_id, modelo_id FROM recorrencias WHERE ativo = 1"
            ).fetchall()
        }

        sugestoes = []
        for chave, linhas_grupo in grupos.items():
            if chave in ja_tem_recorrencia:
                continue
            meses_presentes = {l["mes_ref"] for l in linhas_grupo}
            if not meses_esperados.issubset(meses_presentes):
                continue
            mais_recente = linhas_grupo[0]  # ORDER BY ... n.id DESC dentro do grupo
            sugestoes.append({
                "prestador_id": mais_recente["prestador_id"],
                "prestador_nome": mais_recente["prestador_nome"],
                "prestador_cor": mais_recente["prestador_cor"],
                "tomador_id": mais_recente["tomador_id"],
                "tomador_nome": mais_recente["tomador_nome"],
                "modelo_id": mais_recente["modelo_id"],
                "modelo_descricao": mais_recente["modelo_descricao"],
                "valor_sugerido": mais_recente["valor"],
                "meses_seguidos": len(meses_presentes),
            })
        return sugestoes

    # ------------------------------------------------------------------
    # config (chave/valor livre — smtp, pasta_base, prefs)
    # ------------------------------------------------------------------

    def set_config(self, chave: str, valor: str) -> None:
        self._conn.execute(
            "INSERT INTO config (chave, valor) VALUES (?, ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
            (chave, valor),
        )
        self._conn.commit()

    def get_config(self, chave: str, default: Optional[str] = None) -> Optional[str]:
        linha = self._conn.execute("SELECT valor FROM config WHERE chave = ?", (chave,)).fetchone()
        return linha["valor"] if linha is not None else default
