"""
Cliente SOAP 1.2 para o Web Service NFeDistribuicaoDFe da SEFAZ Nacional.
"""

import base64
import gzip
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .certificate import load_pkcs12_ssl_context
from .constants import SEFAZ_ENDPOINTS, SOAP_ACTION
from .models import SefazQueryResponse
from .rules import distribution_directive


def build_soap_envelope_by_key(
    access_key: str,
    cnpj: str,
    is_homologation: bool = False,
) -> str:
    """
    Gera o envelope SOAP 1.2 oficial para consulta por chave pontual (consChNFe).
    """
    tp_amb = "2" if is_homologation else "1"
    c_uf_autor = access_key[:2]
    clean_cnpj = re.sub(r"\D", "", cnpj)

    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
  <soap12:Body>
    <nfeDistDFeInteresse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">
      <nfeDadosMsg>
        <distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
          <tpAmb>{tp_amb}</tpAmb>
          <cUFAutor>{c_uf_autor}</cUFAutor>
          <CNPJ>{clean_cnpj}</CNPJ>
          <consChNFe>
            <chNFe>{access_key}</chNFe>
          </consChNFe>
        </distDFeInt>
      </nfeDadosMsg>
    </nfeDistDFeInteresse>
  </soap12:Body>
</soap12:Envelope>"""


def build_soap_envelope_by_nsu(
    cnpj: str,
    ult_nsu: str | int = "0",
    c_uf_autor: str = "35",
    is_homologation: bool = False,
) -> str:
    """
    Gera o envelope SOAP 1.2 oficial para consulta e sincronização em lote por NSU (distNSU).
    """
    tp_amb = "2" if is_homologation else "1"
    clean_cnpj = re.sub(r"\D", "", cnpj)
    nsu_str = str(ult_nsu).zfill(15)

    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap12:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
  <soap12:Body>
    <nfeDistDFeInteresse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">
      <nfeDadosMsg>
        <distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
          <tpAmb>{tp_amb}</tpAmb>
          <cUFAutor>{c_uf_autor}</cUFAutor>
          <CNPJ>{clean_cnpj}</CNPJ>
          <distNSU>
            <ultNSU>{nsu_str}</ultNSU>
          </distNSU>
        </distDFeInt>
      </nfeDadosMsg>
    </nfeDistDFeInteresse>
  </soap12:Body>
</soap12:Envelope>"""



def strip_xml_namespaces(xml_text: str) -> str:
    """
    Remove declarações de namespace (xmlns) e seus prefixos de tags e atributos
    de forma segura, evitando erros de 'unbound prefix' no ElementTree.
    """
    if not xml_text:
        return ""
    # 1. Remove prefixos de tags: <prefix:tag> -> <tag> e </prefix:tag> -> </tag>
    clean = re.sub(r'<(/?)[a-zA-Z0-9_]+:([a-zA-Z0-9_]+)', r'<\1\2', xml_text)
    # 2. Remove declarações xmlns e xmlns:prefix="..."
    clean = re.sub(r'\s+xmlns(:\w+)?="[^"]*"', '', clean)
    # 3. Remove prefixos de atributos: prefix:attr="val" -> attr="val"
    clean = re.sub(r'\s+[a-zA-Z0-9_]+:([a-zA-Z0-9_]+)=', r' \1=', clean)
    return clean


def parse_sefaz_response(xml_text: str) -> SefazQueryResponse:
    """
    Extrai as informações de retorno do Web Service da SEFAZ,
    descompactando documentos contidos em <docZip> (base64 + gzip).
    """
    clean_xml = strip_xml_namespaces(xml_text)
    root = ET.fromstring(clean_xml)

    ret = root.find(".//retDistDFeInt")
    if ret is None:
        raise ValueError("Resposta da SEFAZ não contém o nó retDistDFeInt esperado.")

    c_stat_el = ret.find("cStat")
    x_motivo_el = ret.find("xMotivo")
    dh_resp_el = ret.find("dhResp")
    ult_nsu_el = ret.find("ultNSU")
    max_nsu_el = ret.find("maxNSU")

    c_stat = int(c_stat_el.text) if c_stat_el is not None and c_stat_el.text else 0
    x_motivo = x_motivo_el.text if x_motivo_el is not None and x_motivo_el.text else ""
    dh_resp = dh_resp_el.text if dh_resp_el is not None and dh_resp_el.text else datetime.now(timezone.utc).isoformat()
    ult_nsu = ult_nsu_el.text if ult_nsu_el is not None else None
    max_nsu = max_nsu_el.text if max_nsu_el is not None else None

    # Aplica as diretivas fiscais correspondentes ao cStat
    directive = distribution_directive(c_stat, dh_resp)

    documents: list[dict[str, Any]] = []
    lote = ret.find(".//loteDistDFeInt")
    if lote is not None:
        for doc_el in lote.findall("docZip"):
            schema = doc_el.attrib.get("schema", "")
            nsu = doc_el.attrib.get("NSU", "")
            b64_content = (doc_el.text or "").strip()
            if b64_content:
                compressed_bytes = base64.b64decode(b64_content)
                decompressed_xml = gzip.decompress(compressed_bytes).decode("utf-8", errors="replace")
                documents.append({
                    "schema": schema,
                    "nsu": nsu,
                    "xml": decompressed_xml,
                })

    return SefazQueryResponse(
        c_stat=c_stat,
        x_motivo=x_motivo,
        dh_resp=dh_resp,
        ult_nsu=ult_nsu,
        max_nsu=max_nsu,
        documents=documents,
        directive=directive,
        raw_response=xml_text,
    )


def execute_sefaz_query(
    access_key: str,
    cnpj: str,
    cert_path: str | Path,
    cert_password: str,
    is_homologation: bool = False,
    timeout: float = 30.0,
) -> SefazQueryResponse:
    """
    Executa a requisição HTTPS com mTLS para a SEFAZ.
    """
    endpoint = SEFAZ_ENDPOINTS["HOMOLOGACAO" if is_homologation else "PRODUCAO"]
    soap_body = build_soap_envelope_by_key(access_key, cnpj, is_homologation=is_homologation)

    headers = {
        "Content-Type": f'application/soap+xml; charset=utf-8; action="{SOAP_ACTION}"',
        "Accept": "application/soap+xml, text/xml, */*",
        "User-Agent": "DFeCargo-Python-Standalone/1.0",
    }

    with load_pkcs12_ssl_context(cert_path, cert_password) as ssl_ctx:
        with httpx.Client(verify=ssl_ctx, timeout=timeout) as client:
            resp = client.post(endpoint, content=soap_body.encode("utf-8"), headers=headers)
            if resp.status_code not in (200, 500):
                resp.raise_for_status()
            return parse_sefaz_response(resp.text)


def execute_sefaz_nsu_query(
    cnpj: str,
    cert_path: str | Path,
    cert_password: str,
    ult_nsu: str | int = "0",
    c_uf_autor: str = "35",
    is_homologation: bool = False,
    timeout: float = 35.0,
) -> SefazQueryResponse:
    """
    Executa a requisição de consulta por NSU (distNSU) com autenticação mTLS,
    recuperando pacotes de até 50 documentos da SEFAZ.
    """
    endpoint = SEFAZ_ENDPOINTS["HOMOLOGACAO" if is_homologation else "PRODUCAO"]
    soap_body = build_soap_envelope_by_nsu(
        cnpj=cnpj,
        ult_nsu=ult_nsu,
        c_uf_autor=c_uf_autor,
        is_homologation=is_homologation,
    )

    headers = {
        "Content-Type": f'application/soap+xml; charset=utf-8; action="{SOAP_ACTION}"',
        "Accept": "application/soap+xml, text/xml, */*",
        "User-Agent": "DFeCargo-Python-Standalone/1.0",
    }

    with load_pkcs12_ssl_context(cert_path, cert_password) as ssl_ctx:
        with httpx.Client(verify=ssl_ctx, timeout=timeout) as client:
            resp = client.post(endpoint, content=soap_body.encode("utf-8"), headers=headers)
            if resp.status_code not in (200, 500):
                resp.raise_for_status()
            return parse_sefaz_response(resp.text)


