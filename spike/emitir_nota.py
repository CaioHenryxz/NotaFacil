"""Spike Sprint 0 — emite 1 NFS-e no ambiente de homologacao (Producao Restrita)
do Emissor Nacional, via script puro (sem UI).

Uso:
    python emitir_nota.py [config.json]

Ve README.md nesta pasta para o passo a passo completo (onde conseguir um
certificado A1 de teste, como preencher o config.json, como ler o resultado).
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

import httpx
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    pkcs12,
)

import dps_builder as db

# Endpoint da API NFS-e (Sefin Nacional) — POST recebe a DPS, gera a NFS-e sincronamente.
# Fonte: Manual dos Contribuintes - Sistema Nacional NFS-e v1.2 (out/2025), secao 1.3.2(a).
URLS = {
    "homologacao": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional/nfse",
    "producao": "https://sefin.nfse.gov.br/SefinNacional/nfse",
}


def carregar_config(caminho: str) -> Dict[str, Any]:
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def carregar_certificado(caminho_pfx: str, senha: str):
    with open(caminho_pfx, "rb") as f:
        pfx_bytes = f.read()
    chave, certificado, extras = pkcs12.load_key_and_certificates(pfx_bytes, senha.encode("utf-8"))
    if chave is None or certificado is None:
        raise ValueError("Nao foi possivel extrair chave/certificado do .pfx — confira o caminho e a senha.")
    return chave, certificado, list(extras or [])


def escrever_pem_temporarios(chave, certificado, extras) -> tuple[str, str]:
    """mTLS via httpx exige arquivos em disco (certfile, keyfile). Gravados em
    temp e apagados logo apos a chamada — o certificado nunca fica persistido
    fora do .pfx original (mesma logica de 'certificado nunca sai da maquina'
    da espec, secao 4)."""
    cert_pem = certificado.public_bytes(Encoding.PEM)
    for extra in extras:
        cert_pem += extra.public_bytes(Encoding.PEM)
    key_pem = chave.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())

    cert_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    key_file = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    try:
        cert_file.write(cert_pem)
        key_file.write(key_pem)
    finally:
        cert_file.close()
        key_file.close()
    return cert_file.name, key_file.name


def montar_dados_dps(config: Dict[str, Any]) -> db.DadosDPS:
    p, t, s, n = config["prestador"], config["tomador"], config["servico"], config.get("numeracao", {})
    return db.DadosDPS(
        ambiente=config["ambiente"],
        prestador=db.Prestador(
            documento=p["documento"],
            inscricao_municipal=p["inscricao_municipal"],
            codigo_municipio=p["codigo_municipio"],
            opcao_simples_nacional=p.get("opcao_simples_nacional", "1"),
            regime_especial_tributacao=p.get("regime_especial_tributacao", "0"),
        ),
        tomador=db.Tomador(documento=t["documento"], nome=t["nome"], email=t.get("email")),
        servico=db.Servico(
            codigo_tributacao_nacional=s["codigo_tributacao_nacional"],
            codigo_tributacao_municipal=s["codigo_tributacao_municipal"],
            codigo_nbs=s["codigo_nbs"],
            descricao=s["descricao"],
            codigo_municipio_prestacao=s["codigo_municipio_prestacao"],
            valor=s["valor"],
            aliquota_iss=s.get("aliquota_iss"),
            tipo_retencao_issqn=s.get("tipo_retencao_issqn", "1"),
        ),
        numeracao=db.Numeracao(serie=str(n.get("serie", "1")), numero_dps=str(n.get("numero_dps", "1"))),
        data_competencia=config.get("data_competencia"),
    )


def obter_senha_certificado(config: Dict[str, Any]) -> str:
    senha_env_var = config["certificado"].get("senha_env_var", "NFSE_CERT_SENHA")
    senha = os.environ.get(senha_env_var)
    if senha:
        return senha
    import getpass

    return getpass.getpass(f"Senha do certificado ({config['certificado']['caminho_pfx']}): ")


def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).with_name("config.json"))
    if not Path(config_path).exists():
        print(f"Config nao encontrado: {config_path}")
        print("Copie config.exemplo.json para config.json e preencha com seus dados de teste.")
        sys.exit(1)

    config = carregar_config(config_path)
    senha = obter_senha_certificado(config)
    chave, certificado, extras = carregar_certificado(config["certificado"]["caminho_pfx"], senha)

    dados = montar_dados_dps(config)
    dps_sem_assinar = db.montar_dps_xml(dados)
    dps_assinado = db.assinar_dps(dps_sem_assinar, chave, certificado, extras)
    xml_bytes = db.serializar(dps_assinado)

    print("----- DPS assinada (enviada para a API) -----")
    print(xml_bytes.decode("utf-8"))
    print()

    corpo_b64 = base64.b64encode(gzip.compress(xml_bytes)).decode("ascii")
    url = URLS[dados.ambiente]
    print(f"----- POST {url} -----")

    cert_file, key_file = escrever_pem_temporarios(chave, certificado, extras)
    try:
        with httpx.Client(cert=(cert_file, key_file), timeout=60.0) as client:
            resposta = client.post(url, json={"dpsXmlGZipB64": corpo_b64})
    finally:
        os.unlink(cert_file)
        os.unlink(key_file)

    print(f"----- Resposta HTTP {resposta.status_code} -----")
    if resposta.status_code in (200, 201):
        payload = resposta.json()
        chave_acesso = payload.get("chaveAcesso")
        print(f"NFS-e gerada. Chave de acesso: {chave_acesso}")
        if payload.get("nfseXmlGZipB64"):
            nfse_xml = gzip.decompress(base64.b64decode(payload["nfseXmlGZipB64"]))
            saida = Path(f"nfse_{chave_acesso or 'sem_chave'}.xml")
            saida.write_bytes(nfse_xml)
            print(f"XML da NFS-e salvo em: {saida.resolve()}")
    else:
        print("Rejeicao/erro da API:")
        try:
            print(json.dumps(resposta.json(), indent=2, ensure_ascii=False))
        except ValueError:
            print(resposta.text)


if __name__ == "__main__":
    main()
