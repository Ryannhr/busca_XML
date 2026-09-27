"""
Validador e Inspetor de Arquivos XML de NF-e e Documentos Fiscais Eletrônicos (DF-e).
"""

import re
import xml.dom.minidom
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .rules import calculate_nfe_access_key_digit, validate_nfe_access_key

UF_NAMES = {
    "11": "RO - Rondônia",
    "12": "AC - Acre",
    "13": "AM - Amazonas",
    "14": "RR - Roraima",
    "15": "PA - Pará",
    "16": "AP - Amapá",
    "17": "TO - Tocantins",
    "21": "MA - Maranhão",
    "22": "PI - Piauí",
    "23": "CE - Ceará",
    "24": "RN - Rio Grande do Norte",
    "25": "PB - Paraíba",
    "26": "PE - Pernambuco",
    "27": "AL - Alagoas",
    "28": "SE - Sergipe",
    "29": "BA - Bahia",
    "31": "MG - Minas Gerais",
    "32": "ES - Espírito Santo",
    "33": "RJ - Rio de Janeiro",
    "35": "SP - São Paulo",
    "41": "PR - Paraná",
    "42": "SC - Santa Catarina",
    "43": "RS - Rio Grande do Sul",
    "50": "MS - Mato Grosso do Sul",
    "51": "MT - Mato Grosso",
    "52": "GO - Goiás",
    "53": "DF - Distrito Federal",
}

MOD_NAMES = {
    "55": "NF-e (Nota Fiscal Eletrônica)",
    "65": "NFC-e (Nota Fiscal de Consumidor Eletrônica)",
    "57": "CT-e (Conhecimento de Transporte Eletrônico)",
    "58": "MDF-e (Manifesto Eletrônico de Documentos Fiscais)",
}


@dataclass
class XmlValidationReport:
    """Relatório detalhado da validação e inspeção do XML."""
    is_valid_syntax: bool
    is_valid_key: bool
    doc_type: str
    access_key: str | None
    key_details: dict[str, Any] = field(default_factory=dict)
    nfe_data: dict[str, Any] = field(default_factory=dict)
    authorization_data: dict[str, Any] = field(default_factory=dict)
    signature_found: bool = False
    messages: list[dict[str, str]] = field(default_factory=list)  # {"level": "OK"|"WARN"|"ERROR", "text": "..."}
    formatted_xml: str = ""


def format_xml_string(xml_text: str) -> str:
    """Retorna o XML indentado e legível (Pretty Print)."""
    try:
        clean = re.sub(r">\s+<", "><", xml_text.strip())
        dom = xml.dom.minidom.parseString(clean)
        pretty = dom.toprettyxml(indent="  ")
        # Remove linhas em branco geradas pelo minidom
        return "\n".join([line for line in pretty.split("\n") if line.strip()])
    except Exception:
        return xml_text


def inspect_and_validate_xml(xml_content: str) -> XmlValidationReport:
    """
    Analisa a estrutura do XML da NF-e, confere chaves, extrai entidades e valida integridade.
    """
    report = XmlValidationReport(
        is_valid_syntax=False,
        is_valid_key=False,
        doc_type="DESCONHECIDO",
        access_key=None,
    )

    if not xml_content or not xml_content.strip():
        report.messages.append({"level": "ERROR", "text": "Conteúdo XML está vazio."})
        return report

    # 1. Validação de Sintaxe XML
    raw_clean = xml_content.strip()
    if raw_clean.startswith("\ufeff"):  # Remove UTF-8 BOM
        raw_clean = raw_clean[1:]

    try:
        # Cria árvore removendo namespaces e prefixos para busca universal
        from .soap_client import strip_xml_namespaces
        xml_no_ns = strip_xml_namespaces(raw_clean)
        root = ET.fromstring(xml_no_ns)
        report.is_valid_syntax = True
        report.formatted_xml = format_xml_string(raw_clean)
        report.messages.append({"level": "OK", "text": "Sintaxe XML bem-formada e válida."})
    except ET.ParseError as e:
        report.messages.append({"level": "ERROR", "text": f"Erro de sintaxe no XML: {e}"})
        report.formatted_xml = raw_clean
        return report

    # 2. Identificação do Tipo de Documento Fiscal
    root_tag = root.tag.split("}")[-1]
    report.doc_type = root_tag
    report.messages.append({"level": "OK", "text": f"Elemento raiz identificado: <{root_tag}>"})

    # 3. Localização e Validação da Chave de Acesso
    access_key = None

    # Tenta encontrar infNFe Id (ex: Id="NFe352401...")
    inf_nfe = root.find(".//infNFe")
    if inf_nfe is not None:
        raw_id = inf_nfe.attrib.get("Id", "")
        access_key = re.sub(r"\D", "", raw_id)

    # Se não achou no infNFe, procura em nós <chNFe> (ex: eventos, resNFe ou protNFe)
    if not access_key:
        ch_el = root.find(".//chNFe")
        if ch_el is not None and ch_el.text:
            access_key = re.sub(r"\D", "", ch_el.text)

    if access_key and len(access_key) == 44:
        report.access_key = access_key
        key_val = validate_nfe_access_key(access_key)
        report.is_valid_key = key_val.valid

        # Decomposição fiscal da chave
        uf_code = access_key[:2]
        aamm = access_key[2:6]
        emit_cnpj = access_key[6:20]
        mod = access_key[20:22]
        serie = access_key[22:25]
        numero = access_key[25:34]
        tp_emis = access_key[34:35]
        c_nf = access_key[35:43]
        c_dv = access_key[43:44]

        expected_dv = calculate_nfe_access_key_digit(access_key[:43])

        report.key_details = {
            "uf_code": uf_code,
            "uf_name": UF_NAMES.get(uf_code, "UF Desconhecida"),
            "ano_mes": f"20{aamm[:2]}/{aamm[2:]}",
            "emit_cnpj": f"{emit_cnpj[:2]}.{emit_cnpj[2:5]}.{emit_cnpj[5:8]}/{emit_cnpj[8:12]}-{emit_cnpj[12:]}" if len(emit_cnpj) == 14 else emit_cnpj,
            "modelo": f"{mod} - {MOD_NAMES.get(mod, 'Outro')}",
            "serie": int(serie) if serie.isdigit() else serie,
            "numero": int(numero) if numero.isdigit() else numero,
            "tp_emis": tp_emis,
            "c_nf": c_nf,
            "c_dv": c_dv,
            "expected_dv": str(expected_dv),
            "dv_match": (c_dv == str(expected_dv)),
        }

        if key_val.valid:
            report.messages.append({
                "level": "OK",
                "text": f"Chave de Acesso válida (44 dígitos, UF {uf_code}, DV conferido com sucesso: {c_dv})."
            })
        else:
            report.messages.append({
                "level": "ERROR",
                "text": f"Inconsistência na Chave de Acesso: {', '.join(key_val.errors)}"
            })
    elif access_key:
        report.messages.append({
            "level": "WARN",
            "text": f"Chave de acesso encontrada possui {len(access_key)} dígitos (esperado 44)."
        })
    else:
        report.messages.append({
            "level": "WARN",
            "text": "Nenhuma Chave de Acesso de NF-e localizada no documento."
        })

    # 4. Extração de Dados da NF-e (se contiver <infNFe>)
    if inf_nfe is not None:
        ide = inf_nfe.find("ide")
        emit = inf_nfe.find("emit")
        dest = inf_nfe.find("dest")
        total = inf_nfe.find("total/ICMSTot")
        transp = inf_nfe.find("transp")

        nfe_info: dict[str, Any] = {}

        if ide is not None:
            nfe_info["nNF"] = ide.findtext("nNF", "-")
            nfe_info["serie"] = ide.findtext("serie", "-")
            nfe_info["dhEmi"] = ide.findtext("dhEmi") or ide.findtext("dEmi", "-")
            nfe_info["natOp"] = ide.findtext("natOp", "-")
            tp_nf = ide.findtext("tpNF", "")
            nfe_info["tpNF"] = "1 - Saída" if tp_nf == "1" else ("0 - Entrada" if tp_nf == "0" else tp_nf)

        if emit is not None:
            cnpj_el = emit.findtext("CNPJ") or emit.findtext("CPF", "-")
            nfe_info["emit_doc"] = cnpj_el
            nfe_info["emit_nome"] = emit.findtext("xNome", "-")
            nfe_info["emit_fant"] = emit.findtext("xFant", "")
            nfe_info["emit_uf"] = emit.findtext("enderEmit/UF", "-")
            nfe_info["emit_mun"] = emit.findtext("enderEmit/xMun", "-")

        if dest is not None:
            cnpj_dest = dest.findtext("CNPJ") or dest.findtext("CPF") or dest.findtext("idEstrangeiro", "-")
            nfe_info["dest_doc"] = cnpj_dest
            nfe_info["dest_nome"] = dest.findtext("xNome", "-")
            nfe_info["dest_uf"] = dest.findtext("enderDest/UF", "-")
            nfe_info["dest_mun"] = dest.findtext("enderDest/xMun", "-")

        if total is not None:
            nfe_info["vNF"] = total.findtext("vNF", "0.00")
            nfe_info["vProd"] = total.findtext("vProd", "0.00")
            nfe_info["vICMS"] = total.findtext("vICMS", "0.00")
            nfe_info["vFrete"] = total.findtext("vFrete", "0.00")

        if transp is not None:
            nfe_info["transp_nome"] = transp.findtext("transporta/xNome", "Não informado")
            nfe_info["transp_doc"] = transp.findtext("transporta/CNPJ") or transp.findtext("transporta/CPF", "")

        report.nfe_data = nfe_info
        report.messages.append({
            "level": "OK",
            "text": f"Dados da NF-e {nfe_info.get('nNF', '')} Série {nfe_info.get('serie', '')} extraídos com sucesso."
        })

    # 5. Verificação de Protocolo de Autorização (<protNFe>)
    prot_nfe = root.find(".//protNFe/infProt")
    if prot_nfe is not None:
        c_stat = prot_nfe.findtext("cStat", "")
        x_motivo = prot_nfe.findtext("xMotivo", "")
        n_prot = prot_nfe.findtext("nProt", "")
        dh_recbto = prot_nfe.findtext("dhRecbto", "")

        report.authorization_data = {
            "cStat": c_stat,
            "xMotivo": x_motivo,
            "nProt": n_prot,
            "dhRecbto": dh_recbto,
        }

        if c_stat == "100":
            report.messages.append({
                "level": "OK",
                "text": f"Protocolo de Autorização SEFAZ presente: cStat 100 ({x_motivo}) - Prot: {n_prot}"
            })
        else:
            report.messages.append({
                "level": "WARN",
                "text": f"Protocolo de Autorização SEFAZ cStat {c_stat}: {x_motivo} - Prot: {n_prot}"
            })
    else:
        report.messages.append({
            "level": "WARN",
            "text": "Nenhum nó de protocolo de autorização (<protNFe>) encontrado (documento pode ser emissão prévia ou resumo)."
        })

    # 6. Verificação de Assinatura Digital (<Signature>)
    sig = root.find(".//Signature")
    if sig is not None:
        report.signature_found = True
        digest = sig.findtext(".//DigestValue", "")
        report.messages.append({
            "level": "OK",
            "text": f"Assinatura digital X.509 (<Signature>) encontrada. DigestValue: {digest[:15]}..." if digest else "Assinatura digital X.509 encontrada."
        })
    else:
        report.signature_found = False
        report.messages.append({
            "level": "WARN",
            "text": "Assinatura digital (<Signature>) não localizada no XML."
        })

    return report


def validate_xml_file(file_path: str | Path) -> XmlValidationReport:
    """Lê um arquivo do disco e executa o processo de validação e inspeção."""
    p = Path(file_path)
    if not p.exists():
        report = XmlValidationReport(
            is_valid_syntax=False,
            is_valid_key=False,
            doc_type="ARQUIVO_NAO_ENCONTRADO",
            access_key=None,
        )
        report.messages.append({"level": "ERROR", "text": f"Arquivo não encontrado: {p}"})
        return report

    try:
        content = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = p.read_text(encoding="latin-1")
        except Exception as e:
            report = XmlValidationReport(
                is_valid_syntax=False,
                is_valid_key=False,
                doc_type="ERRO_LEITURA",
                access_key=None,
            )
            report.messages.append({"level": "ERROR", "text": f"Não foi possível ler o arquivo: {e}"})
            return report

    return inspect_and_validate_xml(content)

