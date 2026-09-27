"""
Gerador de DANFE (Documento Auxiliar da Nota Fiscal Eletrônica) em PDF a partir do XML.
Compatível com o layout padrão nacional de NF-e (Modelo 55).
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .soap_client import strip_xml_namespaces


def _format_cnpj_cpf(val: str) -> str:
    cleaned = re.sub(r"\D", "", val or "")
    if len(cleaned) == 14:
        return f"{cleaned[:2]}.{cleaned[2:5]}.{cleaned[5:8]}/{cleaned[8:12]}-{cleaned[12:]}"
    if len(cleaned) == 11:
        return f"{cleaned[:3]}.{cleaned[3:6]}.{cleaned[6:9]}-{cleaned[9:]}"
    return val or "-"


def _format_currency(val: str | float | None) -> str:
    if val is None or val == "":
        return "0,00"
    try:
        f = float(str(val).replace(",", "."))
        return f"{f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except ValueError:
        return str(val)


def _format_date(iso_str: str) -> str:
    if not iso_str:
        return "-"
    try:
        # Pega a parte YYYY-MM-DD
        dt_part = iso_str.split("T")[0]
        parts = dt_part.split("-")
        if len(parts) == 3:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
    except Exception:
        pass
    return iso_str[:10]


def _format_time(iso_str: str) -> str:
    if not iso_str or "T" not in iso_str:
        return "-"
    try:
        time_part = iso_str.split("T")[1]
        return time_part[:8]
    except Exception:
        return "-"


def _format_key_grouped(key: str) -> str:
    """Formata a chave de 44 dígitos em grupos de 4 dígitos para fácil conferência visual."""
    cleaned = re.sub(r"\D", "", key or "")
    if len(cleaned) != 44:
        return key or ""
    return " ".join([cleaned[i:i+4] for i in range(0, 44, 4)])


def extract_danfe_data(xml_text: str) -> dict[str, Any]:
    """
    Extrai todos os dados necessários para o DANFE a partir do XML da NF-e.
    """
    clean_xml = strip_xml_namespaces(xml_text.strip())
    root = ET.fromstring(clean_xml)

    inf_nfe = root.find(".//infNFe")
    if inf_nfe is None:
        raise ValueError("O XML informado não contém o elemento <infNFe> de uma NF-e válida.")

    # Chave de Acesso
    raw_id = inf_nfe.attrib.get("Id", "")
    key = re.sub(r"\D", "", raw_id)
    if not key:
        ch_el = root.find(".//chNFe")
        if ch_el is not None and ch_el.text:
            key = re.sub(r"\D", "", ch_el.text)

    # Identificação (<ide>)
    ide = inf_nfe.find("ide") or ET.Element("ide")
    n_nf = ide.findtext("nNF", "-")
    serie = ide.findtext("serie", "1")
    tp_nf = ide.findtext("tpNF", "1")  # 0=Entrada, 1=Saída
    dh_emi = ide.findtext("dhEmi") or ide.findtext("dEmi", "")
    dh_sai_ent = ide.findtext("dhSaiEnt") or ide.findtext("dSaiEnt", "")
    nat_op = ide.findtext("natOp", "VENDA DE MERCADORIA")

    # Emitente (<emit>)
    emit = inf_nfe.find("emit") or ET.Element("emit")
    emit_nome = emit.findtext("xNome", "-")
    emit_fant = emit.findtext("xFant", "")
    emit_cnpj = emit.findtext("CNPJ") or emit.findtext("CPF", "-")
    emit_ie = emit.findtext("IE", "-")
    emit_ie_st = emit.findtext("IEST", "-")
    emit_crt = emit.findtext("CRT", "-")

    ender_emit = emit.find("enderEmit") or ET.Element("enderEmit")
    emit_lgr = ender_emit.findtext("xLgr", "")
    emit_nro = ender_emit.findtext("nro", "S/N")
    emit_cpl = ender_emit.findtext("xCpl", "")
    emit_bairro = ender_emit.findtext("xBairro", "")
    emit_mun = ender_emit.findtext("xMun", "")
    emit_uf = ender_emit.findtext("UF", "")
    emit_cep = ender_emit.findtext("CEP", "")
    emit_fone = ender_emit.findtext("fone", "")

    # Destinatário (<dest>)
    dest = inf_nfe.find("dest") or ET.Element("dest")
    dest_nome = dest.findtext("xNome", "-")
    dest_cnpj = dest.findtext("CNPJ") or dest.findtext("CPF") or dest.findtext("idEstrangeiro", "-")
    dest_ie = dest.findtext("IE", "-")

    ender_dest = dest.find("enderDest") or ET.Element("enderDest")
    dest_lgr = ender_dest.findtext("xLgr", "")
    dest_nro = ender_dest.findtext("nro", "S/N")
    dest_cpl = ender_dest.findtext("xCpl", "")
    dest_bairro = ender_dest.findtext("xBairro", "")
    dest_mun = ender_dest.findtext("xMun", "")
    dest_uf = ender_dest.findtext("UF", "")
    dest_cep = ender_dest.findtext("CEP", "")
    dest_fone = ender_dest.findtext("fone", "")

    # Totais (<total>/<ICMSTot>)
    tot = inf_nfe.find("total/ICMSTot") or ET.Element("ICMSTot")
    v_bc = tot.findtext("vBC", "0.00")
    v_icms = tot.findtext("vICMS", "0.00")
    v_bc_st = tot.findtext("vBCST", "0.00")
    v_st = tot.findtext("vST", "0.00")
    v_prod = tot.findtext("vProd", "0.00")
    v_frete = tot.findtext("vFrete", "0.00")
    v_seg = tot.findtext("vSeg", "0.00")
    v_desc = tot.findtext("vDesc", "0.00")
    v_outro = tot.findtext("vOutro", "0.00")
    v_ipi = tot.findtext("vIPI", "0.00")
    v_nf = tot.findtext("vNF", "0.00")

    # Transporte (<transp>)
    transp = inf_nfe.find("transp") or ET.Element("transp")
    mod_frete = transp.findtext("modFrete", "9")
    mod_frete_map = {
        "0": "0 - Remetente (CIF)",
        "1": "1 - Destinatário (FOB)",
        "2": "2 - Terceiros",
        "3": "3 - Próprio Remetente",
        "4": "4 - Próprio Destinatário",
        "9": "9 - Sem Ocorrência de Transporte",
    }
    frete_desc = mod_frete_map.get(mod_frete, f"{mod_frete} - Outro")

    transporta = transp.find("transporta") or ET.Element("transporta")
    transp_nome = transporta.findtext("xNome", "-")
    transp_cnpj = transporta.findtext("CNPJ") or transporta.findtext("CPF", "-")
    transp_ie = transporta.findtext("IE", "-")
    transp_ender = transporta.findtext("xEnder", "-")
    transp_mun = transporta.findtext("xMun", "-")
    transp_uf = transporta.findtext("UF", "-")

    veic = transp.find("veicTransp") or ET.Element("veicTransp")
    transp_placa = veic.findtext("placa", "-")
    transp_placa_uf = veic.findtext("UF", "-")
    transp_rntc = veic.findtext("RNTC", "-")

    vol = transp.find("vol") or ET.Element("vol")
    transp_q_vol = vol.findtext("qVol", "-")
    transp_esp = vol.findtext("esp", "-")
    transp_marca = vol.findtext("marca", "-")
    transp_n_vol = vol.findtext("nVol", "-")
    transp_peso_b = vol.findtext("pesoB", "-")
    transp_peso_l = vol.findtext("pesoL", "-")

    # Protocolo de Autorização (<protNFe>)
    prot = root.find(".//protNFe/infProt")
    n_prot = prot.findtext("nProt", "-") if prot is not None else "-"
    dh_recbto = prot.findtext("dhRecbto", "") if prot is not None else ""
    c_stat = prot.findtext("cStat", "") if prot is not None else ""

    # Dados Adicionais (<infAdic>)
    inf_adic = inf_nfe.find("infAdic") or ET.Element("infAdic")
    inf_cpl = inf_adic.findtext("infCpl", "")
    inf_fisco = inf_adic.findtext("infAdFisco", "")

    # Produtos (<det>)
    items = []
    for det in inf_nfe.findall("det"):
        prod = det.find("prod")
        if prod is None:
            continue
        imposto = det.find("imposto") or ET.Element("imposto")
        icms_el = imposto.find(".//ICMS/*")
        cst = icms_el.findtext("CST") if icms_el is not None else (icms_el.findtext("CSOSN") if icms_el is not None else "-")
        v_bc_item = icms_el.findtext("vBC", "0.00") if icms_el is not None else "0.00"
        p_icms_item = icms_el.findtext("pICMS", "0.00") if icms_el is not None else "0.00"
        v_icms_item = icms_el.findtext("vICMS", "0.00") if icms_el is not None else "0.00"

        ipi_el = imposto.find(".//IPI/*")
        v_ipi_item = ipi_el.findtext("vIPI", "0.00") if ipi_el is not None else "0.00"
        p_ipi_item = ipi_el.findtext("pIPI", "0.00") if ipi_el is not None else "0.00"

        items.append({
            "cProd": prod.findtext("cProd", "-"),
            "xProd": prod.findtext("xProd", "-"),
            "NCM": prod.findtext("NCM", "-"),
            "CST": cst or "-",
            "CFOP": prod.findtext("CFOP", "-"),
            "uCom": prod.findtext("uCom", "UN"),
            "qCom": prod.findtext("qCom", "1"),
            "vUnCom": prod.findtext("vUnCom", "0.00"),
            "vProd": prod.findtext("vProd", "0.00"),
            "vBC": v_bc_item,
            "vICMS": v_icms_item,
            "vIPI": v_ipi_item,
            "pICMS": p_icms_item,
            "pIPI": p_ipi_item,
        })

    return {
        "key": key,
        "nNF": n_nf,
        "serie": serie,
        "tpNF": tp_nf,
        "dhEmi": dh_emi,
        "dhSaiEnt": dh_sai_ent,
        "natOp": nat_op,
        "emit": {
            "nome": emit_nome,
            "fant": emit_fant,
            "cnpj": emit_cnpj,
            "ie": emit_ie,
            "ie_st": emit_ie_st,
            "endereco": f"{emit_lgr}, {emit_nro}" + (f" - {emit_cpl}" if emit_cpl else ""),
            "bairro": emit_bairro,
            "mun": emit_mun,
            "uf": emit_uf,
            "cep": emit_cep,
            "fone": emit_fone,
        },
        "dest": {
            "nome": dest_nome,
            "cnpj": dest_cnpj,
            "ie": dest_ie,
            "endereco": f"{dest_lgr}, {dest_nro}" + (f" - {dest_cpl}" if dest_cpl else ""),
            "bairro": dest_bairro,
            "mun": dest_mun,
            "uf": dest_uf,
            "cep": dest_cep,
            "fone": dest_fone,
        },
        "totais": {
            "vBC": v_bc,
            "vICMS": v_icms,
            "vBCST": v_bc_st,
            "vST": v_st,
            "vProd": v_prod,
            "vFrete": v_frete,
            "vSeg": v_seg,
            "vDesc": v_desc,
            "vOutro": v_outro,
            "vIPI": v_ipi,
            "vNF": v_nf,
        },
        "transp": {
            "frete_desc": frete_desc,
            "nome": transp_nome,
            "cnpj": transp_cnpj,
            "ie": transp_ie,
            "endereco": transp_ender,
            "mun": transp_mun,
            "uf": transp_uf,
            "placa": transp_placa,
            "placa_uf": transp_placa_uf,
            "rntc": transp_rntc,
            "qVol": transp_q_vol,
            "esp": transp_esp,
            "marca": transp_marca,
            "nVol": transp_n_vol,
            "pesoB": transp_peso_b,
            "pesoL": transp_peso_l,
        },
        "prot": {
            "nProt": n_prot,
            "dhRecbto": dh_recbto,
            "cStat": c_stat,
        },
        "infAdic": {
            "infCpl": inf_cpl,
            "infFisco": inf_fisco,
        },
        "items": items,
    }


class DanfePdfRenderer:
    """Renderizador vetorial de DANFE no padrão A4 oficial."""

    def __init__(self, data: dict[str, Any], output_path: Path):
        self.data = data
        self.output_path = output_path
        self.page_w, self.page_h = A4
        self.margin_x = 15.0
        self.content_w = self.page_w - (2 * self.margin_x)

    def draw_box(
        self,
        c: canvas.Canvas,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str = "",
        value: str = "",
        title_size: int = 5,
        value_size: int = 7,
        value_bold: bool = True,
        align: str = "left",
        fill: bool = False,
    ) -> None:
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)
        if fill:
            c.setFillColor(colors.HexColor("#f0f0f0"))
            c.rect(x, y, w, h, fill=1, stroke=1)
        else:
            c.rect(x, y, w, h, fill=0, stroke=1)

        if title:
            c.setFillColor(colors.HexColor("#333333"))
            c.setFont("Helvetica", title_size)
            c.drawString(x + 2, y + h - (title_size + 1), title.upper())

        if value:
            c.setFillColor(colors.black)
            font_name = "Helvetica-Bold" if value_bold else "Helvetica"
            c.setFont(font_name, value_size)
            val_y = y + 2.5
            if align == "right":
                c.drawRightString(x + w - 3, val_y, str(value))
            elif align == "center":
                c.drawCentredString(x + (w / 2), val_y, str(value))
            else:
                c.drawString(x + 2, val_y, str(value))

    def render(self) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        c = canvas.Canvas(str(self.output_path), pagesize=A4)
        c.setTitle(f"DANFE NF-e {self.data['nNF']} Série {self.data['serie']}")

        d = self.data
        curr_y = self.page_h - 15.0

        # =====================================================================
        # 1. CANHOTO DE RECEBIMENTO
        # =====================================================================
        canhoto_h = 32.0
        canhoto_y = curr_y - canhoto_h

        # Caixa esquerda do canhoto
        left_canhoto_w = self.content_w - 95.0
        c.setLineWidth(0.5)
        c.setStrokeColor(colors.black)
        c.rect(self.margin_x, canhoto_y, left_canhoto_w, canhoto_h)

        c.setFont("Helvetica", 5.5)
        c.setFillColor(colors.black)
        c.drawString(
            self.margin_x + 3,
            canhoto_y + canhoto_h - 7,
            f"RECEBEMOS DE {d['emit']['nome'][:60]} OS PRODUTOS/SERVIÇOS CONSTANTES DA NOTA FISCAL INDICADA AO LADO",
        )

        # Divisão da data e assinatura
        c.line(self.margin_x, canhoto_y + 16, self.margin_x + left_canhoto_w, canhoto_y + 16)
        c.line(self.margin_x + 100, canhoto_y, self.margin_x + 100, canhoto_y + 16)

        c.drawString(self.margin_x + 2, canhoto_y + 10, "DATA DE RECEBIMENTO")
        c.drawString(self.margin_x + 103, canhoto_y + 10, "IDENTIFICAÇÃO E ASSINATURA DO RECEBEDOR")

        # Caixa direita do canhoto (Número da NF-e)
        right_canhoto_x = self.margin_x + left_canhoto_w
        c.rect(right_canhoto_x, canhoto_y, 95.0, canhoto_h)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(right_canhoto_x + 47.5, canhoto_y + 20, "NF-e")
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(right_canhoto_x + 47.5, canhoto_y + 10, f"Nº {d['nNF']}")
        c.setFont("Helvetica", 7)
        c.drawCentredString(right_canhoto_x + 47.5, canhoto_y + 2, f"Série {d['serie']}")

        # Linha pontilhada separadora
        curr_y = canhoto_y - 4
        c.setDash(2, 2)
        c.line(self.margin_x, curr_y, self.margin_x + self.content_w, curr_y)
        c.setDash()

        # =====================================================================
        # 2. CABEÇALHO / IDENTIFICAÇÃO DO EMITENTE & DANFE
        # =====================================================================
        header_h = 100.0
        curr_y -= header_h

        # Caixa 1: Emitente (esquerda)
        emit_box_w = 215.0
        c.rect(self.margin_x, curr_y, emit_box_w, header_h)

        c.setFont("Helvetica-Bold", 9)
        c.drawString(self.margin_x + 4, curr_y + header_h - 12, d["emit"]["nome"][:35])
        if d["emit"]["fant"]:
            c.setFont("Helvetica-Bold", 8)
            c.drawString(self.margin_x + 4, curr_y + header_h - 22, d["emit"]["fant"][:38])

        c.setFont("Helvetica", 7)
        c.drawString(self.margin_x + 4, curr_y + header_h - 35, d["emit"]["endereco"][:45])
        c.drawString(self.margin_x + 4, curr_y + header_h - 45, f"{d['emit']['bairro']} - CEP: {d['emit']['cep']}")
        c.drawString(self.margin_x + 4, curr_y + header_h - 55, f"{d['emit']['mun']} - {d['emit']['uf']}")
        if d["emit"]["fone"]:
            c.drawString(self.margin_x + 4, curr_y + header_h - 65, f"Fone: {d['emit']['fone']}")

        # Caixa 2: Identificação do DANFE (centro)
        danfe_box_x = self.margin_x + emit_box_w
        danfe_box_w = 110.0
        c.rect(danfe_box_x, curr_y, danfe_box_w, header_h)

        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString(danfe_box_x + (danfe_box_w / 2), curr_y + header_h - 16, "DANFE")
        c.setFont("Helvetica", 6)
        c.drawCentredString(danfe_box_x + (danfe_box_w / 2), curr_y + header_h - 25, "Documento Auxiliar da")
        c.drawCentredString(danfe_box_x + (danfe_box_w / 2), curr_y + header_h - 32, "Nota Fiscal Eletrônica")

        # Entrada / Saída
        tp_box_x = danfe_box_x + (danfe_box_w / 2) - 10
        c.rect(tp_box_x, curr_y + header_h - 52, 20, 14)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(tp_box_x + 10, curr_y + header_h - 50, d["tpNF"])

        c.setFont("Helvetica", 6)
        c.drawString(danfe_box_x + 6, curr_y + header_h - 44, "0 - ENTRADA")
        c.drawString(danfe_box_x + 6, curr_y + header_h - 50, "1 - SAÍDA")

        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(danfe_box_x + (danfe_box_w / 2), curr_y + header_h - 68, f"Nº {d['nNF']}")
        c.drawCentredString(danfe_box_x + (danfe_box_w / 2), curr_y + header_h - 78, f"SÉRIE: {d['serie']}")
        c.setFont("Helvetica", 7)
        c.drawCentredString(danfe_box_x + (danfe_box_w / 2), curr_y + header_h - 88, "FOLHA 1/1")

        # Caixa 3: Controle do Fisco e Código de Barras (direita)
        fisco_box_x = danfe_box_x + danfe_box_w
        fisco_box_w = self.content_w - (emit_box_w + danfe_box_w)
        c.rect(fisco_box_x, curr_y, fisco_box_w, header_h)

        # Código de barras Code 128
        if d["key"] and len(d["key"]) == 44:
            try:
                barcode = createBarcodeDrawing(
                    "Code128",
                    value=d["key"],
                    barWidth=0.72,
                    barHeight=24,
                    humanReadable=False,
                )
                barcode.drawOn(c, fisco_box_x + 8, curr_y + header_h - 32)
            except Exception:
                pass

        c.setFont("Helvetica", 5.5)
        c.drawString(fisco_box_x + 4, curr_y + header_h - 38, "CHAVE DE ACESSO")
        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString(fisco_box_x + (fisco_box_w / 2), curr_y + header_h - 48, _format_key_grouped(d["key"]))

        c.setFont("Helvetica", 6)
        c.drawString(
            fisco_box_x + 4,
            curr_y + header_h - 60,
            "Consulta de autenticidade no portal nacional da NF-e",
        )
        c.drawString(
            fisco_box_x + 4,
            curr_y + header_h - 67,
            "www.nfe.fazenda.gov.br/portal ou no site da SEFAZ Autorizadora",
        )

        c.line(fisco_box_x, curr_y + 26, fisco_box_x + fisco_box_w, curr_y + 26)
        c.setFont("Helvetica", 5.5)
        c.drawString(fisco_box_x + 4, curr_y + 20, "PROTOCOLO DE AUTORIZAÇÃO DE USO")
        c.setFont("Helvetica-Bold", 7.5)
        prot_str = f"{d['prot']['nProt']} - {_format_date(d['prot']['dhRecbto'])} {_format_time(d['prot']['dhRecbto'])}"
        c.drawString(fisco_box_x + 4, curr_y + 8, prot_str)

        # =====================================================================
        # 3. NATUREZA DA OPERAÇÃO, INSCRIÇÕES
        # =====================================================================
        row_h = 18.0
        curr_y -= row_h
        self.draw_box(c, self.margin_x, curr_y, self.content_w - 240, row_h, "NATUREZA DA OPERAÇÃO", d["natOp"], 5, 7)
        self.draw_box(c, self.margin_x + self.content_w - 240, curr_y, 240, row_h, "PROTOCOLO DE AUTORIZAÇÃO DE USO", prot_str, 5, 7)

        curr_y -= row_h
        ie_w = self.content_w / 3
        self.draw_box(c, self.margin_x, curr_y, ie_w, row_h, "INSCRIÇÃO ESTADUAL", d["emit"]["ie"])
        self.draw_box(c, self.margin_x + ie_w, curr_y, ie_w, row_h, "INSC. ESTADUAL DO SUBST. TRIB.", d["emit"]["ie_st"])
        self.draw_box(c, self.margin_x + (ie_w * 2), curr_y, ie_w, row_h, "CNPJ", _format_cnpj_cpf(d["emit"]["cnpj"]))

        # =====================================================================
        # 4. DESTINATÁRIO / REMETENTE
        # =====================================================================
        curr_y -= 13
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(self.margin_x, curr_y + 3, "DESTINATÁRIO / REMETENTE")

        curr_y -= row_h
        self.draw_box(c, self.margin_x, curr_y, self.content_w - 220, row_h, "NOME / RAZÃO SOCIAL", d["dest"]["nome"])
        self.draw_box(c, self.margin_x + self.content_w - 220, curr_y, 140, row_h, "CNPJ / CPF", _format_cnpj_cpf(d["dest"]["cnpj"]))
        self.draw_box(c, self.margin_x + self.content_w - 80, curr_y, 80, row_h, "DATA DA EMISSÃO", _format_date(d["dhEmi"]))

        curr_y -= row_h
        self.draw_box(c, self.margin_x, curr_y, self.content_w - 220, row_h, "ENDEREÇO", d["dest"]["endereco"])
        self.draw_box(c, self.margin_x + self.content_w - 220, curr_y, 140, row_h, "BAIRRO / DISTRITO", d["dest"]["bairro"])
        self.draw_box(c, self.margin_x + self.content_w - 80, curr_y, 80, row_h, "DATA SAÍDA/ENTRADA", _format_date(d["dhSaiEnt"]))

        curr_y -= row_h
        col_dest_w = (self.content_w - 80) / 4
        self.draw_box(c, self.margin_x, curr_y, col_dest_w * 1.5, row_h, "MUNICÍPIO", d["dest"]["mun"])
        self.draw_box(c, self.margin_x + (col_dest_w * 1.5), curr_y, col_dest_w * 0.8, row_h, "FONE / FAX", d["dest"]["fone"])
        self.draw_box(c, self.margin_x + (col_dest_w * 2.3), curr_y, col_dest_w * 0.5, row_h, "UF", d["dest"]["uf"])
        self.draw_box(c, self.margin_x + (col_dest_w * 2.8), curr_y, col_dest_w * 1.2, row_h, "INSCRIÇÃO ESTADUAL", d["dest"]["ie"])
        self.draw_box(c, self.margin_x + self.content_w - 80, curr_y, 80, row_h, "HORA SAÍDA", _format_time(d["dhSaiEnt"]))

        # =====================================================================
        # 5. CÁLCULO DO IMPOSTO
        # =====================================================================
        curr_y -= 13
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(self.margin_x, curr_y + 3, "CÁLCULO DO IMPOSTO")

        curr_y -= row_h
        col5 = self.content_w / 5
        self.draw_box(c, self.margin_x, curr_y, col5, row_h, "BASE DE CÁLCULO DO ICMS", _format_currency(d["totais"]["vBC"]), align="right")
        self.draw_box(c, self.margin_x + col5, curr_y, col5, row_h, "VALOR DO ICMS", _format_currency(d["totais"]["vICMS"]), align="right")
        self.draw_box(c, self.margin_x + (col5 * 2), curr_y, col5, row_h, "BASE CÁLC. ICMS SUBST.", _format_currency(d["totais"]["vBCST"]), align="right")
        self.draw_box(c, self.margin_x + (col5 * 3), curr_y, col5, row_h, "VALOR DO ICMS SUBST.", _format_currency(d["totais"]["vST"]), align="right")
        self.draw_box(c, self.margin_x + (col5 * 4), curr_y, col5, row_h, "VALOR TOTAL DOS PRODUTOS", _format_currency(d["totais"]["vProd"]), align="right")

        curr_y -= row_h
        col6 = self.content_w / 6
        self.draw_box(c, self.margin_x, curr_y, col6, row_h, "VALOR DO FRETE", _format_currency(d["totais"]["vFrete"]), align="right")
        self.draw_box(c, self.margin_x + col6, curr_y, col6, row_h, "VALOR DO SEGURO", _format_currency(d["totais"]["vSeg"]), align="right")
        self.draw_box(c, self.margin_x + (col6 * 2), curr_y, col6, row_h, "DESCONTO", _format_currency(d["totais"]["vDesc"]), align="right")
        self.draw_box(c, self.margin_x + (col6 * 3), curr_y, col6, row_h, "OUTRAS DESP. ACESSÓRIAS", _format_currency(d["totais"]["vOutro"]), align="right")
        self.draw_box(c, self.margin_x + (col6 * 4), curr_y, col6, row_h, "VALOR TOTAL DO IPI", _format_currency(d["totais"]["vIPI"]), align="right")
        self.draw_box(c, self.margin_x + (col6 * 5), curr_y, col6, row_h, "VALOR TOTAL DA NOTA", _format_currency(d["totais"]["vNF"]), align="right", value_size=8)

        # =====================================================================
        # 6. TRANSPORTADOR / VOLUMES TRANSPORTADOS
        # =====================================================================
        curr_y -= 13
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(self.margin_x, curr_y + 3, "TRANSPORTADOR / VOLUMES TRANSPORTADOS")

        curr_y -= row_h
        self.draw_box(c, self.margin_x, curr_y, self.content_w - 320, row_h, "RAZÃO SOCIAL", d["transp"]["nome"])
        self.draw_box(c, self.margin_x + self.content_w - 320, curr_y, 110, row_h, "FRETE POR CONTA", d["transp"]["frete_desc"][:20])
        self.draw_box(c, self.margin_x + self.content_w - 210, curr_y, 50, row_h, "CÓDIGO ANTT", d["transp"]["rntc"])
        self.draw_box(c, self.margin_x + self.content_w - 160, curr_y, 50, row_h, "PLACA VEÍC.", d["transp"]["placa"])
        self.draw_box(c, self.margin_x + self.content_w - 110, curr_y, 25, row_h, "UF", d["transp"]["placa_uf"])
        self.draw_box(c, self.margin_x + self.content_w - 85, curr_y, 85, row_h, "CNPJ / CPF", _format_cnpj_cpf(d["transp"]["cnpj"]))

        curr_y -= row_h
        self.draw_box(c, self.margin_x, curr_y, self.content_w - 220, row_h, "ENDEREÇO", d["transp"]["endereco"])
        self.draw_box(c, self.margin_x + self.content_w - 220, curr_y, 140, row_h, "MUNICÍPIO", d["transp"]["mun"])
        self.draw_box(c, self.margin_x + self.content_w - 80, curr_y, 30, row_h, "UF", d["transp"]["uf"])
        self.draw_box(c, self.margin_x + self.content_w - 50, curr_y, 50, row_h, "INSC. ESTADUAL", d["transp"]["ie"])

        curr_y -= row_h
        vol_w = self.content_w / 6
        self.draw_box(c, self.margin_x, curr_y, vol_w, row_h, "QUANTIDADE", d["transp"]["qVol"])
        self.draw_box(c, self.margin_x + vol_w, curr_y, vol_w, row_h, "ESPÉCIE", d["transp"]["esp"])
        self.draw_box(c, self.margin_x + (vol_w * 2), curr_y, vol_w, row_h, "MARCA", d["transp"]["marca"])
        self.draw_box(c, self.margin_x + (vol_w * 3), curr_y, vol_w, row_h, "NUMERAÇÃO", d["transp"]["nVol"])
        self.draw_box(c, self.margin_x + (vol_w * 4), curr_y, vol_w, row_h, "PESO BRUTO", d["transp"]["pesoB"])
        self.draw_box(c, self.margin_x + (vol_w * 5), curr_y, vol_w, row_h, "PESO LÍQUIDO", d["transp"]["pesoL"])

        # =====================================================================
        # 7. DADOS DOS PRODUTOS / SERVIÇOS
        # =====================================================================
        curr_y -= 13
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(self.margin_x, curr_y + 3, "DADOS DOS PRODUTOS / SERVIÇOS")

        # Cabeçalho da Tabela de Produtos
        th_h = 12.0
        curr_y -= th_h
        cols = [
            ("CÓD. PROD", 50.0),
            ("DESCRIÇÃO DO PRODUTO / SERVIÇO", 185.0),
            ("NCM/SH", 45.0),
            ("CST", 25.0),
            ("CFOP", 25.0),
            ("UN", 20.0),
            ("QTD", 35.0),
            ("V. UNIT", 45.0),
            ("V. TOTAL", 45.0),
            ("BC ICMS", 40.0),
            ("V. ICMS", 35.0),
            ("ALÍQ ICMS", 25.0),
        ]
        # Ajusta última coluna para fechar perfeitamente a largura da página
        total_w = sum(w for _, w in cols)
        diff = self.content_w - total_w
        cols[1] = (cols[1][0], cols[1][1] + diff)

        cx = self.margin_x
        for col_name, w in cols:
            self.draw_box(c, cx, curr_y, w, th_h, title=col_name, title_size=5, fill=True)
            cx += w

        # Linhas de Itens
        item_h = 10.0
        max_items_page_1 = 12  # Cabe até 12 itens na primeira folha
        items_to_print = d["items"][:max_items_page_1]

        for it in items_to_print:
            curr_y -= item_h
            cx = self.margin_x
            col_data = [
                (it["cProd"][:10], "left"),
                (it["xProd"][:42], "left"),
                (it["NCM"][:8], "center"),
                (it["CST"][:3], "center"),
                (it["CFOP"][:4], "center"),
                (it["uCom"][:3], "center"),
                (_format_currency(it["qCom"]), "right"),
                (_format_currency(it["vUnCom"]), "right"),
                (_format_currency(it["vProd"]), "right"),
                (_format_currency(it["vBC"]), "right"),
                (_format_currency(it["vICMS"]), "right"),
                (f"{float(it['pICMS']):.0f}%" if it.get("pICMS") else "0%", "center"),
            ]
            for i, (val, align) in enumerate(col_data):
                w = cols[i][1]
                c.setStrokeColor(colors.HexColor("#dddddd"))
                c.rect(cx, curr_y, w, item_h, fill=0, stroke=1)
                c.setFillColor(colors.black)
                c.setFont("Helvetica", 6)
                if align == "right":
                    c.drawRightString(cx + w - 2, curr_y + 2.5, val)
                elif align == "center":
                    c.drawCentredString(cx + (w / 2), curr_y + 2.5, val)
                else:
                    c.drawString(cx + 2, curr_y + 2.5, val)
                cx += w

        # Espaço restante da tabela até os dados adicionais
        extra_space_y = 75.0
        if curr_y > extra_space_y + 30:
            c.setStrokeColor(colors.black)
            c.rect(self.margin_x, extra_space_y + 25, self.content_w, curr_y - (extra_space_y + 25))

        # =====================================================================
        # 8. DADOS ADICIONAIS
        # =====================================================================
        adic_h = 75.0
        adic_y = 15.0

        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(self.margin_x, adic_y + adic_h + 3, "DADOS ADICIONAIS")

        fisco_w = 170.0
        cpl_w = self.content_w - fisco_w

        # Caixa Informações Complementares
        c.rect(self.margin_x, adic_y, cpl_w, adic_h)
        c.setFont("Helvetica", 5.5)
        c.setFillColor(colors.HexColor("#333333"))
        c.drawString(self.margin_x + 3, adic_y + adic_h - 8, "INFORMAÇÕES COMPLEMENTARES")

        # Texto das informações complementares quebrado em linhas
        c.setFont("Helvetica", 5.5)
        c.setFillColor(colors.black)
        cpl_text = d["infAdic"]["infCpl"].replace("\r\n", " ").replace("\n", " ").strip()
        words = cpl_text.split()
        lines = []
        cur_line = ""
        for w in words:
            if len(cur_line) + len(w) + 1 <= 95:
                cur_line += (" " if cur_line else "") + w
            else:
                lines.append(cur_line)
                cur_line = w
                if len(lines) >= 8:
                    break
        if cur_line and len(lines) < 8:
            lines.append(cur_line)

        ty = adic_y + adic_h - 18
        for l in lines:
            c.drawString(self.margin_x + 3, ty, l)
            ty -= 7

        # Caixa Reservado ao Fisco
        c.rect(self.margin_x + cpl_w, adic_y, fisco_w, adic_h)
        c.setFont("Helvetica", 5.5)
        c.setFillColor(colors.HexColor("#333333"))
        c.drawString(self.margin_x + cpl_w + 3, adic_y + adic_h - 8, "RESERVADO AO FISCO")

        c.showPage()
        c.save()
        return self.output_path


def generate_danfe_pdf(
    xml_input: str | Path,
    output_pdf_path: str | Path | None = None,
) -> Path:
    """
    Função pública de alto nível para gerar o DANFE em PDF a partir do XML.
    Recebe o caminho para um arquivo .xml ou a string com o conteúdo XML.
    """
    if isinstance(xml_input, (str, Path)) and os.path.exists(str(xml_input)):
        p = Path(xml_input)
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = p.read_text(encoding="latin-1")
    else:
        content = str(xml_input)

    data = extract_danfe_data(content)

    if output_pdf_path is None:
        key = data.get("key") or f"nfe_{data.get('nNF')}"
        default_dir = Path(__file__).resolve().parent.parent.parent / "sefaz_data" / "danfes"
        default_dir.mkdir(parents=True, exist_ok=True)
        output_pdf_path = default_dir / f"DANFE_{key}.pdf"
    else:
        output_pdf_path = Path(output_pdf_path)

    renderer = DanfePdfRenderer(data, output_pdf_path)
    return renderer.render()


def open_pdf_file(pdf_path: str | Path) -> None:
    """Abre o arquivo PDF no visualizador padrão do sistema operacional."""
    p = Path(pdf_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Arquivo PDF não encontrado: {p}")

    if sys.platform.startswith("win"):
        os.startfile(str(p))
    elif sys.platform.startswith("darwin"):
        import subprocess
        subprocess.run(["open", str(p)], check=False)
    else:
        import subprocess
        subprocess.run(["xdg-open", str(p)], check=False)


def detect_document_type(xml_or_key: str) -> str:
    """
    Identifica se o documento é CT-e (Modelo 57/67) ou NF-e (Modelo 55)
    a partir da chave de acesso de 44 dígitos ou do conteúdo XML.
    Retorna 'CTE' ou 'NFE'.
    """
    raw = str(xml_or_key).strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 44:
        modelo = digits[20:22]
        if modelo in ("57", "67"):
            return "CTE"
        return "NFE"

    if "<CTe" in raw or "<cteProc" in raw or "<infCte" in raw:
        return "CTE"
    return "NFE"


def generate_fiscal_document_pdf(
    xml_input: str | Path,
    output_pdf_path: str | Path | None = None,
) -> tuple[str, Path]:
    """
    Despachante inteligente: detecta automaticamente se o XML é NF-e ou CT-e
    e gera o documento auxiliar em PDF correspondente (DANFE para NF-e ou DACTE para CT-e).
    Retorna uma tupla: (tipo: 'NFE' | 'CTE', caminho_pdf: Path).
    """
    if isinstance(xml_input, (str, Path)) and os.path.exists(str(xml_input)):
        p = Path(xml_input)
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = p.read_text(encoding="latin-1")
    else:
        content = str(xml_input)

    doc_type = detect_document_type(content)
    if doc_type == "CTE":
        from .dacte_generator import generate_dacte_pdf
        pdf_path = generate_dacte_pdf(content, output_pdf_path)
        return ("CTE", pdf_path)
    else:
        pdf_path = generate_danfe_pdf(content, output_pdf_path)
        return ("NFE", pdf_path)


