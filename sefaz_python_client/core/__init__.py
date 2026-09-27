"""
Pacote principal do cliente SEFAZ DF-e.
"""

from .constants import DFE_POINT_QUERY_LIMITS, SEFAZ_ENDPOINTS, SOAP_ACTION, VALID_UF_CODES
from .models import DistributionDirective, NfeAccessKeyValidation, SefazQueryResponse
from .rules import (
    calculate_nfe_access_key_digit,
    classify_transport_eligibility,
    distribution_directive,
    normalize_fiscal_identity,
    validate_nfe_access_key,
)
from .certificate import load_pkcs12_ssl_context
from .registry import SefazLocalRegistry
from .soap_client import build_soap_envelope_by_key, execute_sefaz_query, parse_sefaz_response
from .service import run_self_tests, search_nfe_xml
from .xml_validator import XmlValidationReport, format_xml_string, inspect_and_validate_xml, validate_xml_file
from .batch_processor import (
    BatchFolderValidator,
    BatchQueryItem,
    BatchQueryManager,
    BatchXmlAuditRow,
    extract_keys_from_file,
    extract_keys_from_text,
)
from .danfe_generator import (
    detect_document_type,
    extract_danfe_data,
    generate_danfe_pdf,
    generate_fiscal_document_pdf,
    open_pdf_file,
)
from .dacte_generator import extract_dacte_data, generate_dacte_pdf

__all__ = [
    "VALID_UF_CODES",
    "DFE_POINT_QUERY_LIMITS",
    "SEFAZ_ENDPOINTS",
    "SOAP_ACTION",
    "NfeAccessKeyValidation",
    "DistributionDirective",
    "SefazQueryResponse",
    "calculate_nfe_access_key_digit",
    "validate_nfe_access_key",
    "normalize_fiscal_identity",
    "classify_transport_eligibility",
    "distribution_directive",
    "load_pkcs12_ssl_context",
    "SefazLocalRegistry",
    "build_soap_envelope_by_key",
    "parse_sefaz_response",
    "execute_sefaz_query",
    "search_nfe_xml",
    "run_self_tests",
    "XmlValidationReport",
    "format_xml_string",
    "inspect_and_validate_xml",
    "validate_xml_file",
    "BatchQueryItem",
    "BatchQueryManager",
    "BatchFolderValidator",
    "BatchXmlAuditRow",
    "extract_keys_from_text",
    "extract_keys_from_file",
    "detect_document_type",
    "extract_danfe_data",
    "generate_danfe_pdf",
    "extract_dacte_data",
    "generate_dacte_pdf",
    "generate_fiscal_document_pdf",
    "open_pdf_file",
]
