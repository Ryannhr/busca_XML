"""
Gerenciamento de Certificado Digital A1 (.pfx / .p12) e autenticação mTLS.
"""

import contextlib
import os
import ssl
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
except ImportError:
    print("ERRO: Pacote 'cryptography' não encontrado. Instale com: pip install cryptography", file=sys.stderr)
    raise


def inspect_certificate(
    pfx_path: str | Path,
    password: str | bytes,
) -> dict[str, Any]:
    """
    Inspeciona o arquivo de certificado A1 (.pfx/.p12), validando a senha,
    a integridade e o prazo de validade (expirado vs válido).
    """
    pfx_file = Path(pfx_path)
    if not pfx_file.exists():
        raise FileNotFoundError(f"Arquivo de certificado não encontrado: {pfx_path}")

    pfx_bytes = pfx_file.read_bytes()
    pwd_bytes = password.encode("utf-8") if isinstance(password, str) else password

    try:
        private_key, cert, additional_certs = pkcs12.load_key_and_certificates(
            pfx_bytes,
            pwd_bytes,
        )
    except Exception as e:
        err_str = str(e).lower()
        if "password" in err_str or "pkcs12" in err_str or "mac" in err_str or "padding" in err_str:
            raise ValueError("A senha informada para o certificado digital A1 está incorreta.") from e
        raise ValueError(f"Não foi possível ler o arquivo PKCS#12 do certificado: {e}") from e

    if cert is None:
        raise ValueError("O arquivo .pfx/.p12 não contém um certificado X.509 válido.")

    if private_key is None:
        raise ValueError("O arquivo .pfx/.p12 não contém uma chave privada associada (necessária para mTLS).")

    # Extrai datas de validade
    if hasattr(cert, "not_valid_after_utc"):
        not_after = cert.not_valid_after_utc
        not_before = cert.not_valid_before_utc
    else:
        not_after = cert.not_valid_after.replace(tzinfo=timezone.utc)
        not_before = cert.not_valid_before.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    is_expired = now > not_after
    is_not_yet_valid = now < not_before

    # Extrai nome do titular (Subject Common Name)
    common_names = cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
    subject_cn = common_names[0].value if common_names else "Desconhecido"

    # Extrai emissor
    issuer_cns = cert.issuer.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
    issuer_cn = issuer_cns[0].value if issuer_cns else "Desconhecido"

    return {
        "valid": not is_expired and not is_not_yet_valid,
        "is_expired": is_expired,
        "is_not_yet_valid": is_not_yet_valid,
        "subject_cn": subject_cn,
        "issuer_cn": issuer_cn,
        "valid_from": not_before.strftime("%d/%m/%Y %H:%M:%S UTC"),
        "valid_until": not_after.strftime("%d/%m/%Y %H:%M:%S UTC"),
        "private_key": private_key,
        "cert": cert,
        "additional_certs": additional_certs or [],
    }


@contextlib.contextmanager
def load_pkcs12_ssl_context(
    pfx_path: str | Path,
    password: str | bytes,
) -> Generator[ssl.SSLContext, None, None]:
    """
    Lê o certificado A1 (.pfx ou .p12) usando cryptography e gera um contexto
    SSL temporário e seguro para autenticação mTLS (Client Certificate) com a SEFAZ.
    Garante limpeza imediata dos arquivos temporários de chave privada.
    """
    info = inspect_certificate(pfx_path, password)

    if info["is_expired"]:
        raise ValueError(
            f"O Certificado Digital A1 ({info['subject_cn']}) está EXPIRADO desde {info['valid_until']}! "
            "A SEFAZ rejeita conexões com certificados vencidos. É necessário utilizar um certificado válido."
        )

    if info["is_not_yet_valid"]:
        raise ValueError(
            f"O Certificado Digital A1 ainda não está ativo (válido a partir de {info['valid_from']})."
        )

    private_key = info["private_key"]
    cert = info["cert"]
    additional_certs = info["additional_certs"]

    # Converte chave e certificado para PEM em disco temporário com permissões restritas
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    chain_pem = b"".join([cert_pem] + [
        c.public_bytes(serialization.Encoding.PEM) for c in additional_certs
    ])

    temp_dir = tempfile.mkdtemp(prefix="sefaz_mtls_")
    cert_path = os.path.join(temp_dir, "cert_chain.pem")
    key_path = os.path.join(temp_dir, "key.pem")

    try:
        with open(cert_path, "wb") as f:
            f.write(chain_pem)
        with open(key_path, "wb") as f:
            f.write(key_pem)

        ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        yield ctx
    finally:
        # Destruição segura dos arquivos temporários
        for p in (cert_path, key_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        if os.path.exists(temp_dir):
            try:
                os.rmdir(temp_dir)
            except OSError:
                pass
