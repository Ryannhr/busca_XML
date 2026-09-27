"""
Serviço de busca, download e orquestração do cliente SEFAZ DF-e.
"""

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import DistributionDirective
from .registry import SefazLocalRegistry
from .rules import (
    calculate_nfe_access_key_digit,
    classify_transport_eligibility,
    distribution_directive,
    validate_nfe_access_key,
)
from .soap_client import execute_sefaz_query


def search_nfe_xml(
    access_key: str,
    cnpj: str,
    cert_path: str | Path,
    cert_password: str,
    is_homologation: bool = False,
    registry: SefazLocalRegistry | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Orquestra a busca do XML respeitando:
    1. Validação estrita da chave de 44 dígitos;
    2. Consulta em cache seguro local (evitando consumo de cota);
    3. Verificação de travas e limite de consultas por hora;
    4. Conexão real com a SEFAZ via mTLS;
    5. Tratamento de diretivas e armazenamento do XML baixado.
    """
    if registry is None:
        registry = SefazLocalRegistry()

    # 1. Validação da Chave
    validation = validate_nfe_access_key(access_key)
    if not validation.valid:
        return {
            "status": "VALIDATION_FAILED",
            "access_key": access_key,
            "errors": validation.errors,
            "message": f"Chave de acesso inválida: {', '.join(validation.errors)}",
        }

    key = validation.normalized

    # 2. Verificação de Cache
    cached_file = registry.get_cached_xml(key)
    if cached_file:
        return {
            "status": "CACHE_HIT",
            "access_key": key,
            "file_path": str(cached_file),
            "content": cached_file.read_text(encoding="utf-8"),
            "message": f"Documento localizado no cache seguro local ({cached_file.name}); nenhuma chamada externa foi consumida.",
        }

    # 3. Verificação de Taxa e Bloqueio
    allowed, block_msg = registry.check_rate_limit()
    if not allowed:
        return {
            "status": "RATE_LIMITED",
            "access_key": key,
            "message": block_msg,
        }

    if dry_run:
        return {
            "status": "DRY_RUN_READY",
            "access_key": key,
            "message": "Chave válida e taxa disponível. Pronto para consulta real.",
        }

    # 4. Validação Prévia do Certificado Digital A1 (evita chamadas inúteis e protege a cota horária)
    from .certificate import inspect_certificate
    try:
        cert_info = inspect_certificate(cert_path, cert_password)
        if cert_info["is_expired"]:
            return {
                "status": "CERTIFICATE_EXPIRED",
                "access_key": key,
                "message": f"Certificado Digital A1 ({cert_info['subject_cn']}) está EXPIRADO desde {cert_info['valid_until']}. Nenhuma consulta foi consumida.",
            }
        if cert_info["is_not_yet_valid"]:
            return {
                "status": "CERTIFICATE_NOT_YET_VALID",
                "access_key": key,
                "message": f"Certificado Digital A1 ainda não está ativo (válido a partir de {cert_info['valid_from']}).",
            }
    except Exception as e:
        return {
            "status": "CERTIFICATE_ERROR",
            "access_key": key,
            "message": f"Falha no Certificado Digital A1: {e}",
        }

    # 5. Transmissão Real para a SEFAZ
    registry.register_query_attempt(access_key=key, cnpj=cnpj)
    try:
        response = execute_sefaz_query(
            access_key=key,
            cnpj=cnpj,
            cert_path=cert_path,
            cert_password=cert_password,
            is_homologation=is_homologation,
        )
    except Exception as e:
        return {
            "status": "COMMUNICATION_ERROR",
            "access_key": key,
            "message": f"Falha na comunicação com a SEFAZ: {e}",
        }

    # 5. Registro da Diretiva (Pausas para cStat 137 ou 656)
    registry.register_directive(response.directive)

    saved_files: list[str] = []
    xml_content = None

    if response.c_stat == 138 and response.documents:
        # Documentos localizados e descompactados
        for doc in response.documents:
            xml_text = doc["xml"]
            # Salva o arquivo principal
            fp = registry.store_xml(key, xml_text, c_stat=response.c_stat)
            saved_files.append(str(fp))
            xml_content = xml_text

        return {
            "status": "SUCCESS",
            "access_key": key,
            "c_stat": response.c_stat,
            "x_motivo": response.x_motivo,
            "saved_files": saved_files,
            "content": xml_content,
            "message": f"XML baixado com sucesso! Salvo em: {', '.join(saved_files)}",
        }

    return {
        "status": "SEFAZ_RESPONSE",
        "access_key": key,
        "c_stat": response.c_stat,
        "x_motivo": response.x_motivo,
        "directive": asdict(response.directive),
        "message": f"SEFAZ retornou cStat {response.c_stat}: {response.x_motivo} (Diretiva: {response.directive.action} - {response.directive.reason})",
    }


def run_self_tests() -> None:
    """Executa a bateria de testes de paridade das regras fiscais."""
    print("Iniciando testes de paridade das regras fiscais...\n")

    # 1. Teste de cálculo de dígito verificador
    base_43 = "3524011234567800019555001000000001100000001"
    digit = calculate_nfe_access_key_digit(base_43)
    full_key = f"{base_43}{digit}"
    print(f"[OK] Digito verificador gerado: {digit}")

    # 2. Teste de validação de chave válida
    val = validate_nfe_access_key(full_key)
    assert val.valid, f"Falha esperava válido, erros: {val.errors}"
    print("[OK] Validacao de chave valida: OK")

    # 3. Teste de chave com dígito incorreto
    invalid_digit_key = f"{base_43}{(digit + 1) % 10}"
    val_inv = validate_nfe_access_key(invalid_digit_key)
    assert not val_inv.valid and "INVALID_CHECK_DIGIT" in val_inv.errors
    print("[OK] Deteccao de digito verificador incorreto: OK")

    # 4. Teste de UF inválida
    inv_uf_key = f"99{full_key[2:]}"
    val_uf = validate_nfe_access_key(inv_uf_key)
    assert not val_uf.valid and "INVALID_UF_CODE" in val_uf.errors
    print("[OK] Deteccao de UF invalida: OK")

    # 5. Teste de diretivas de distribuição
    dir_137 = distribution_directive(137, "2026-09-19T10:00:00Z")
    assert dir_137.action == "WAIT" and "NO_DOCUMENTS_WAIT_65_MINUTES" in dir_137.reason
    print("[OK] Diretiva cStat 137 (espera 65 min): OK")

    dir_656 = distribution_directive(656, "2026-09-19T10:00:00Z")
    assert dir_656.action == "BLOCK" and "UNDUE_CONSUMPTION" in dir_656.reason
    print("[OK] Diretiva cStat 656 (bloqueio por consumo indevido): OK")

    dir_138 = distribution_directive(138, "2026-09-19T10:00:00Z")
    assert dir_138.action == "PROCESS" and dir_138.reason == "DOCUMENTS_LOCATED"
    print("[OK] Diretiva cStat 138 (documentos localizados): OK")

    # 6. Teste de elegibilidade do transportador
    elig = classify_transport_eligibility("12.345.678/0001-95", transporter_cnpj="12345678000195")
    assert elig == "TRANSPORTA"
    print("[OK] Elegibilidade de transportador: OK")

    print("\nTodos os testes de regras fiscais passaram com 100% de sucesso!")

