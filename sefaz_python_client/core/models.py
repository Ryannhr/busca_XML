"""
Modelos de dados e dataclasses do cliente SEFAZ DF-e.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NfeAccessKeyValidation:
    """Resultado da validação da chave de acesso de 44 dígitos."""
    valid: bool
    normalized: str
    errors: tuple[str, ...]


@dataclass(frozen=True)
class DistributionDirective:
    """Diretiva fiscal resultante do cStat da SEFAZ."""
    action: str  # "PROCESS", "WAIT", "BLOCK", "RECONCILE", "RETRY", "FAIL"
    next_allowed_at: str | None
    reason: str


@dataclass
class SefazQueryResponse:
    """Resposta estruturada da consulta ao Web Service SEFAZ."""
    c_stat: int
    x_motivo: str
    dh_resp: str
    ult_nsu: str | None
    max_nsu: str | None
    documents: list[dict[str, Any]]
    directive: DistributionDirective
    raw_response: str

