"""
Regras de negócio fiscais para validação de chave NF-e, diretivas cStat e elegibilidade.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Sequence

from .constants import VALID_UF_CODES
from .models import DistributionDirective, NfeAccessKeyValidation


def calculate_nfe_access_key_digit(first43_digits: str) -> int:
    """
    Calcula o dígito verificador ponderado (Módulo 11) dos primeiros 43 dígitos da NF-e.
    Pesos de 2 a 9, da direita para a esquerda.
    """
    if len(first43_digits) != 43 or not first43_digits.isdigit():
        raise ValueError("NFE_ACCESS_KEY_BASE_MUST_HAVE_43_DIGITS")
    weight = 2
    total = 0
    for ch in reversed(first43_digits):
        total += int(ch) * weight
        weight = 2 if weight == 9 else weight + 1
    remainder = total % 11
    return 0 if remainder in (0, 1) else 11 - remainder


def validate_nfe_access_key(value: str) -> NfeAccessKeyValidation:
    """
    Valida a integridade da chave de acesso da NF-e:
    - Exatamente 44 dígitos numéricos
    - Código de UF válido (11 a 53)
    - Mês de emissão entre 01 e 12
    - Modelo fixo 55 (NF-e)
    - Dígito verificador conforme Módulo 11
    """
    normalized = "".join(value.split())
    errors: list[str] = []

    if len(normalized) != 44 or not normalized.isdigit():
        errors.append("ACCESS_KEY_MUST_HAVE_44_DIGITS")
        return NfeAccessKeyValidation(valid=False, normalized=normalized, errors=tuple(errors))

    if normalized[:2] not in VALID_UF_CODES:
        errors.append("INVALID_UF_CODE")

    month = int(normalized[4:6])
    if month < 1 or month > 12:
        errors.append("INVALID_ISSUE_MONTH")

    # Modelos aceitos no DF-e: 55 (NF-e), 57 (CT-e) e 67 (CT-e OS)
    if normalized[20:22] not in ("55", "57", "67"):
        errors.append("INVALID_DOCUMENT_MODEL")

    expected_digit = calculate_nfe_access_key_digit(normalized[:43])
    if int(normalized[43]) != expected_digit:
        errors.append("INVALID_CHECK_DIGIT")

    return NfeAccessKeyValidation(valid=len(errors) == 0, normalized=normalized, errors=tuple(errors))


def normalize_fiscal_identity(value: str | None) -> str | None:
    """Normaliza CNPJ para 14 caracteres alfanuméricos em caixa alta."""
    if not value:
        return None
    normalized = re.sub(r"[^0-9A-Za-z]", "", value).upper()
    return normalized if len(normalized) == 14 else None


def classify_transport_eligibility(
    queried_establishment_cnpj: str,
    transporter_cnpj: str | None = None,
    interested_transport_actor_event_cnpjs: Sequence[str] | None = None,
    full_xml_available: bool = False,
) -> str:
    """
    Classifica a elegibilidade fiscal do consulente:
    - TRANSPORTA: CNPJ consulente coincide com o transportador indicado na NF-e
    - TRANSPORT_EVENT_110150: CNPJ manifestado por evento de ator interessado
    - PENDING_FULL_XML / NOT_ELIGIBLE
    """
    queried = normalize_fiscal_identity(queried_establishment_cnpj)
    if not queried:
        return "NOT_ELIGIBLE"

    if normalize_fiscal_identity(transporter_cnpj) == queried:
        return "TRANSPORTA"

    if interested_transport_actor_event_cnpjs:
        for cnpj in interested_transport_actor_event_cnpjs:
            if normalize_fiscal_identity(cnpj) == queried:
                return "TRANSPORT_EVENT_110150"

    return "NOT_ELIGIBLE" if full_xml_available else "PENDING_FULL_XML"


def _plus_minutes(iso_timestamp: str, minutes: int) -> str:
    try:
        ts = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    except ValueError:
        ts = datetime.now(timezone.utc)
    return (ts + timedelta(minutes=minutes)).isoformat()


def distribution_directive(c_stat: int, dh_resp: str) -> DistributionDirective:
    """
    Aplica diretivas do Web Service de Distribuição de DF-e conforme o cStat da SEFAZ:
    - 137: Nenhum documento localizado -> aguardar 65 minutos
    - 656: Consumo indevido -> bloqueio estrito de 65 minutos em todos os métodos
    - 108 / 109: Serviço paralisado ou portal indisponível -> retry com backoff
    - 589: Cursor defasado -> reconciliação de cursor
    - 138: Documentos localizados -> processar lote
    """
    if c_stat == 137:
        return DistributionDirective(
            action="WAIT",
            next_allowed_at=_plus_minutes(dh_resp, 65),
            reason="NO_DOCUMENTS_WAIT_65_MINUTES",
        )
    if c_stat == 656:
        return DistributionDirective(
            action="BLOCK",
            next_allowed_at=_plus_minutes(dh_resp, 65),
            reason="UNDUE_CONSUMPTION_BLOCK_ALL_METHODS",
        )
    if c_stat in (108, 109):
        return DistributionDirective(
            action="RETRY",
            next_allowed_at=None,
            reason="PORTAL_UNAVAILABLE_BACKOFF_REQUIRED",
        )
    if c_stat == 589:
        return DistributionDirective(
            action="RECONCILE",
            next_allowed_at=None,
            reason="CURSOR_MUST_NOT_ADVANCE",
        )
    if c_stat == 138:
        return DistributionDirective(
            action="PROCESS",
            next_allowed_at=None,
            reason="DOCUMENTS_LOCATED",
        )
    return DistributionDirective(
        action="FAIL",
        next_allowed_at=None,
        reason=f"UNMAPPED_CSTAT_{c_stat}",
    )

