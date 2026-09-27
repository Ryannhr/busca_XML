"""
Gerador de DACTE (Documento Auxiliar do Conhecimento de Transporte Eletrônico) em PDF a partir do XML.
Compatível com o layout oficial de CT-e (Modelo 57 - Rodoviário e Outros Modais).
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
        dt_part = iso_str.split("T")[0]
        parts = dt_part.split("-")
        if len(parts) == 3:
            return f"{parts[2]}/{parts[1]}/{parts[0]}"
    except Exception:
        pass
    return iso_str[:10]


def _format_datetime(iso_str: str) -> str:
    if not iso_str:
        return "-"
    try:
        if "T" in iso_str:
            d_part, t_part = iso_str.split("T")
            d_fmt = _format_date(d_part)
            t_fmt = t_part[:8]
            return f"{d_fmt} {t_fmt}"
        return _format_date(iso_str)
    except Exception:
        return iso_str


def _format_key_grouped(key: str) -> str:
    cleaned = re.sub(r"\D", "", key or "")
    if len(cleaned) != 44:
        return key or ""
    return ".".join([cleaned[i:i+4] for i in range(0, 44, 4)])


def extract_dacte_data(xml_text: str) -> dict[str, Any]:
    """
    Extrai todos os dados estruturados do XML do CT-e para a geração do DACTE.
    """
    clean_xml = strip_xml_namespaces(xml_text.strip())
    root = ET.fromstring(clean_xml)

    inf_cte = root.find(".//infCte")
    if inf_cte is None:
        raise ValueError("O XML informado não contém o elemento <infCte> de um CT-e válido.")

    # Chave de Acesso
    raw_id = inf_cte.attrib.get("Id", "")
    key = re.sub(r"\D", "", raw_id)
    if not key:
        ch_el = root.find(".//chCTe")
        if ch_el is not None and ch_el.text:
            key = re.sub(r"\D", "", ch_el.text)

    # Identificação (<ide>)
    ide = inf_cte.find("ide") or ET.Element("ide")
    n_ct = ide.findtext("nCT", "-")
    serie = ide.findtext("serie", "1")
    cfop = ide.findtext("CFOP", "-")
    nat_op = ide.findtext("natOp", "PRESTACAO DE SERVICO DE TRANSPORTE")
    dh_emi = ide.findtext("dhEmi", "")
    tp_imp = ide.findtext("tpImp", "1")
    tp_emis = ide.findtext("tpEmis", "1")
    tp_amb = ide.findtext("tpAmb", "1")

    # Modais: 01=Rodoviário, 02=Aéreo, 03=Aquaviário, 04=Ferroviário, 05=Dutoviário, 06=Multimodal
    modal_code = ide.findtext("modal", "01")
    modais_map = {
        "01": "RODOVIÁRIO",
        "02": "AÉREO",
        "03": "AQUAVIÁRIO",
        "04": "FERROVIÁRIO",
        "05": "DUTOVIÁRIO",
        "06": "MULTIMODAL",
    }
    modal_desc = modais_map.get(modal_code, "RODOVIÁRIO")

    # Tipo do CTe: 0=Normal, 1=Complemento, 2=Anulação, 3=Substituto
    tp_cte_code = ide.findtext("tpCTe", "0")
    tp_cte_map = {"0": "NORMAL", "1": "COMPLEMENTAR", "2": "ANULAÇÃO", "3": "SUBSTITUTO"}
    tp_cte_desc = tp_cte_map.get(tp_cte_code, "NORMAL")

    # Tipo do Serviço: 0=Normal, 1=Subcontratação, 2=Redespacho, 3=Redespacho Intermediário, 4=Vinculado a Multimodal
    tp_serv_code = ide.findtext("tpServ", "0")
    tp_serv_map = {
        "0": "NORMAL",
        "1": "SUBCONTRATAÇÃO",
        "2": "REDESPACHO",
        "3": "REDESPACHO INTERMEDIÁRIO",
        "4": "VINCULADO A MULTIMODAL",
    }
    tp_serv_desc = tp_serv_map.get(tp_serv_code, "NORMAL")

    ind_globalizado = "S" if ide.findtext("indGlobalizado") == "1" else "N"

    # Início e Fim da Prestação
    x_mun_ini = ide.findtext("xMunIni", "-")
    uf_ini = ide.findtext("UFIni", "-")
    x_mun_fim = ide.findtext("xMunFim", "-")
    uf_fim = ide.findtext("UFFim", "-")

    # Tomador de Serviço (<toma3> ou <toma4>)
    # 0=Remetente, 1=Expedidor, 2=Recebedor, 3=Destinatário, 4=Outros
    toma_code = "0"
    toma3 = ide.find("toma3")
    if toma3 is not None:
        toma_code = toma3.findtext("toma", "0")

    # Protocolo de Autorização
    prot = root.find(".//protCTe/infProt")
    c_stat = prot.findtext("cStat") if prot is not None else ""
    n_prot = prot.findtext("nProt") if prot is not None else "-"
    dh_recbto = prot.findtext("dhRecbto") if prot is not None else ""

    # Parse de participante auxiliar
    def _parse_part(el_name: str) -> dict[str, str]:
        el = inf_cte.find(el_name)
        if el is None:
            return {}
        ender = el.find(f"ender{el_name.capitalize()[:4]}")
        if ender is None:
            # fallback para nomes alternativos de endereço
            ender = el.find("enderEmit") or el.find("enderReme") or el.find("enderDest") or el.find("enderExped") or el.find("enderReceb") or el.find("enderToma")

        doc = el.findtext("CNPJ") or el.findtext("CPF", "")
        nome = el.findtext("xNome", "-")
        fant = el.findtext("xFant", "")
        ie = el.findtext("IE", "-")
        fone = el.findtext("fone", "")
        isuf = el.findtext("ISUF", "")

        lgr = ender.findtext("xLgr", "") if ender is not None else ""
        nro = ender.findtext("nro", "") if ender is not None else ""
        cpl = ender.findtext("xCpl", "") if ender is not None else ""
        bairro = ender.findtext("xBairro", "") if ender is not None else ""
        mun = ender.findtext("xMun", "") if ender is not None else ""
        uf = ender.findtext("UF", "") if ender is not None else ""
        cep = ender.findtext("CEP", "") if ender is not None else ""
        pais = ender.findtext("xPais", "BRASIL") if ender is not None else "BRASIL"

        logradouro_completo = f"{lgr}, {nro}".strip(", ")
        if bairro:
            logradouro_completo += f" - {bairro}"

        return {
            "nome": nome,
            "fant": fant,
            "doc": doc,
            "doc_fmt": _format_cnpj_cpf(doc),
            "ie": ie,
            "fone": fone,
            "isuf": isuf,
            "endereco": logradouro_completo,
            "complemento": cpl,
            "bairro": bairro,
            "municipio": mun,
            "uf": uf,
            "cep": f"{cep[:5]}-{cep[5:]}" if len(cep) == 8 else cep,
            "pais": pais,
        }

    emit = _parse_part("emit")
    rem = _parse_part("rem")
    dest = _parse_part("dest")
    exped = _parse_part("exped")
    receb = _parse_part("receb")

    # Identificação do Tomador do Serviço
    toma_info: dict[str, str] = {}
    toma_desc = "REMETENTE"
    if toma_code == "0" and rem:
        toma_info = rem.copy()
        toma_desc = "REMETENTE"
    elif toma_code == "1" and exped:
        toma_info = exped.copy()
        toma_desc = "EXPEDIDOR"
    elif toma_code == "2" and receb:
        toma_info = receb.copy()
        toma_desc = "RECEBEDOR"
    elif toma_code == "3" and dest:
        toma_info = dest.copy()
        toma_desc = "DESTINATÁRIO"
    else:
        toma4 = inf_cte.find("toma4")
        if toma4 is not None:
            toma_info = _parse_part("toma4")
            toma_desc = "OUTROS"
        elif rem:
            toma_info = rem.copy()
            toma_desc = "REMETENTE"

    # Valores da Prestação (<vPrest>)
    v_prest = inf_cte.find("vPrest") or ET.Element("vPrest")
    v_t_prest = v_prest.findtext("vTPrest", "0.00")
    v_rec = v_prest.findtext("vRec", v_t_prest)

    componentes: list[dict[str, str]] = []
    for comp in v_prest.findall("Comp"):
        componentes.append({
            "nome": comp.findtext("xNome", "COMPONENTE"),
            "valor": _format_currency(comp.findtext("vComp", "0.00")),
        })

    # Informações de Imposto (<imp>)
    imp = inf_cte.find("imp") or ET.Element("imp")
    cst = "-"
    cst_desc = "Outros"
    v_bc = "0.00"
    p_icms = "0.00"
    v_icms = "0.00"
    p_red_bc = "0.00"
    v_cred = "0.00"

    icms_el = imp.find("ICMS")
    if icms_el is not None and len(icms_el) > 0:
        icms_child = icms_el[0]
        cst = icms_child.findtext("CST", "-")
        v_bc = icms_child.findtext("vBC", "0.00")
        p_icms = icms_child.findtext("pICMS", "0.00")
        v_icms = icms_child.findtext("vICMS", "0.00")
        p_red_bc = icms_child.findtext("pRedBC", "0.00")
        v_cred = icms_child.findtext("vCred", "0.00")

        cst_map = {
            "00": "00 - Tributação Integral",
            "20": "20 - Tributação com Redução de BC",
            "40": "40 - ICMS Isenção",
            "41": "41 - ICMS Não Tributado",
            "51": "51 - ICMS Diferido",
            "60": "60 - ICMS Cobrado Anteriormente por ST",
            "90": "90 - ICMS Outros",
            "SN": "Simples Nacional",
        }
        cst_desc = cst_map.get(cst, f"{cst} - Tributação CT-e")

    # Informações da Carga (<infCarga>)
    inf_cte_norm = inf_cte.find("infCTeNorm") or inf_cte
    inf_carga = inf_cte_norm.find("infCarga") or ET.Element("infCarga")
    v_carga = inf_carga.findtext("vCarga", "0.00")
    pro_pred = inf_carga.findtext("proPred", "-")
    x_out_cat = inf_carga.findtext("xOutCat", "-")

    quantidades: list[dict[str, str]] = []
    for q in inf_carga.findall("infQ"):
        unid_code = q.findtext("cUnid", "01")
        unid_map = {"00": "M3", "01": "KG", "02": "TON", "03": "UN", "04": "LT", "05": "MMBTU"}
        quantidades.append({
            "unidade": unid_map.get(unid_code, "KG"),
            "tipo_medida": q.findtext("tpMed", "PESO"),
            "qtd": _format_currency(q.findtext("qCarga", "0.0000")),
        })

    # Seguro da Carga (<seg>)
    seg = inf_cte_norm.find("seg")
    seg_info = {
        "responsavel": "-",
        "seguradora": "-",
        "apolice": "-",
        "v_aver": "0.00",
        "n_aver": "-",
    }
    if seg is not None:
        resp_code = seg.findtext("respSeg", "1")
        resp_map = {"1": "REMETENTE", "2": "EXPEDIDOR", "3": "RECEBEDOR", "4": "DESTINATÁRIO", "5": "EMITENTE CT-E", "6": "TOMADOR"}
        seg_info = {
            "responsavel": resp_map.get(resp_code, "EMISSOR CT-e"),
            "seguradora": seg.findtext("xSeg", "-"),
            "apolice": seg.findtext("nApol", "-"),
            "v_aver": _format_currency(seg.findtext("vCarga") or seg.findtext("vAver", "0.00")),
            "n_aver": seg.findtext("nAver", "-"),
        }

    # Documentos Originários (NF-e, NF, Outros em <infDoc>)
    docs_originarios: list[dict[str, str]] = []
    inf_doc = inf_cte_norm.find("infDoc")
    if inf_doc is not None:
        for inf_nfe in inf_doc.findall("infNFe"):
            ch_doc = inf_nfe.findtext("chave", "-")
            # Extrai cnpj e serie/num a partir da chave da nfe
            cnpj_doc = "-"
            serie_num_doc = "-"
            if len(ch_doc) == 44:
                cnpj_doc = _format_cnpj_cpf(ch_doc[6:20])
                serie_num_doc = f"{int(ch_doc[22:25])}/{int(ch_doc[25:34])}"
            docs_originarios.append({
                "tipo": "NFE",
                "doc_emit": cnpj_doc,
                "serie_num": serie_num_doc,
                "chave": ch_doc,
            })
        for inf_nf in inf_doc.findall("infNF"):
            docs_originarios.append({
                "tipo": "NF",
                "doc_emit": "-",
                "serie_num": f"{inf_nf.findtext('serie', '-')}/{inf_nf.findtext('nDoc', '-')}",
                "chave": "-",
            })

    # Modal Rodoviário (<rodo>)
    rodo = inf_cte_norm.find("rodo")
    rntrc = "-"
    veiculos = []
    motoristas = []
    if rodo is not None:
        rntrc = rodo.findtext("RNTRC", "-")
        for veic in rodo.findall("veic"):
            veiculos.append({
                "placa": veic.findtext("placa", "-"),
                "renavam": veic.findtext("RENAVAM", "-"),
                "uf": veic.findtext("UF", "-"),
            })
        for moto in rodo.findall("moto"):
            motoristas.append({
                "nome": moto.findtext("xNome", "-"),
                "cpf": _format_cnpj_cpf(moto.findtext("CPF", "")),
            })

    # Observações (<compl>)
    compl = inf_cte.find("compl")
    obs_text_parts = []
    if compl is not None:
        x_obs = compl.findtext("xObs")
        if x_obs:
            obs_text_parts.append(x_obs.strip())
        for obs_cont in compl.findall("ObsCont"):
            x_campo = obs_cont.attrib.get("xCampo", "")
            x_texto = obs_cont.findtext("xTexto", "")
            if x_texto:
                obs_text_parts.append(f"{x_campo}: {x_texto}")

    # Dados adicionais do fisco
    inf_ad_fisco = imp.findtext("infAdFisco")
    if inf_ad_fisco:
        obs_text_parts.append(f"Fisco: {inf_ad_fisco.strip()}")

    observacoes = " | ".join(obs_text_parts) if obs_text_parts else "-"

    return {
        "key": key,
        "nCT": n_ct,
        "serie": serie,
        "cfop": cfop,
        "natOp": nat_op,
        "dhEmi": dh_emi,
        "modal": modal_desc,
        "tpCTe": tp_cte_desc,
        "tpServ": tp_serv_desc,
        "indGlobalizado": ind_globalizado,
        "xMunIni": x_mun_ini,
        "ufIni": uf_ini,
        "xMunFim": x_mun_fim,
        "ufFim": uf_fim,
        "nProt": n_prot,
        "dhRecbto": dh_recbto,
        "cStat": c_stat,
        "emit": emit,
        "rem": rem,
        "dest": dest,
        "exped": exped,
        "receb": receb,
        "tomador": toma_info,
        "tomador_tipo": toma_desc,
        "vTPrest": _format_currency(v_t_prest),
        "vRec": _format_currency(v_rec),
        "componentes": componentes,
        "cst_desc": cst_desc,
        "vBC": _format_currency(v_bc),
        "pICMS": _format_currency(p_icms),
        "vICMS": _format_currency(v_icms),
        "pRedBC": _format_currency(p_red_bc),
        "vCred": _format_currency(v_cred),
        "vCarga": _format_currency(v_carga),
        "proPred": pro_pred,
        "xOutCat": x_out_cat,
        "quantidades": quantidades,
        "seguro": seg_info,
        "docs_originarios": docs_originarios,
        "rntrc": rntrc,
        "veiculos": veiculos,
        "motoristas": motoristas,
        "observacoes": observacoes,
    }


class DactePdfRenderer:
    """
    Renderizador do DACTE em formato PDF A4 utilizando ReportLab.
    Segue rigorosamente as proporções e seções do layout nacional do CT-e.
    """

    def __init__(self, data: dict[str, Any], output_path: str | Path):
        self.data = data
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        self.c = canvas.Canvas(str(self.output_path), pagesize=A4)
        self.width, self.height = A4  # 595.27 x 841.89

        self.margin_x = 20
        self.printable_width = self.width - (2 * self.margin_x)  # 555.27
        self.y = self.height - 20

    def draw_box(self, x: float, y: float, w: float, h: float, fill_color: colors.Color | None = None) -> None:
        self.c.saveState()
        self.c.setLineWidth(0.6)
        self.c.setStrokeColor(colors.black)
        if fill_color:
            self.c.setFillColor(fill_color)
            self.c.rect(x, y, w, h, fill=1, stroke=1)
        else:
            self.c.rect(x, y, w, h, fill=0, stroke=1)
        self.c.restoreState()

    def draw_text(self, text: str, x: float, y: float, size: float = 7, bold: bool = False, color: colors.Color = colors.black) -> None:
        self.c.saveState()
        font_name = "Helvetica-Bold" if bold else "Helvetica"
        self.c.setFont(font_name, size)
        self.c.setFillColor(color)
        self.c.drawString(x, y, str(text))
        self.c.restoreState()

    def draw_text_right(self, text: str, x: float, y: float, size: float = 7, bold: bool = False) -> None:
        self.c.saveState()
        font_name = "Helvetica-Bold" if bold else "Helvetica"
        self.c.setFont(font_name, size)
        self.c.drawRightString(x, y, str(text))
        self.c.restoreState()

    def draw_text_center(self, text: str, x: float, y: float, size: float = 7, bold: bool = False) -> None:
        self.c.saveState()
        font_name = "Helvetica-Bold" if bold else "Helvetica"
        self.c.setFont(font_name, size)
        self.c.drawCentredString(x, y, str(text))
        self.c.restoreState()

    def render(self) -> Path:
        self._render_canhoto_superior()
        self._render_cabecalho_dacte()
        self._render_tipo_cte_e_servico()
        self._render_inicio_fim_prestacao()
        self._render_atores_transporte()
        self._render_dados_carga_e_seguro()
        self._render_componentes_prestacao()
        self._render_informacoes_imposto()
        self._render_documentos_originarios()
        self._render_observacoes()
        self._render_rodape()

        self.c.save()
        return self.output_path

    def _render_canhoto_superior(self) -> None:
        h = 50
        y_box = self.y - h
        w = self.printable_width
        x = self.margin_x

        self.draw_box(x, y_box, w, h)

        # Texto do cabeçalho do canhoto
        self.draw_text_center(
            "DECLARO QUE RECEBI OS VOLUMES DESTE CONHECIMENTO EM PERFEITO ESTADO PELO QUE DOU POR CUMPRIMENTO O PRESENTE CONTRATO DE TRANSPORTE",
            x + (w / 2),
            y_box + h - 9,
            size=5.5,
            bold=True,
        )

        self.c.setLineWidth(0.4)
        self.c.line(x, y_box + h - 12, x + w, y_box + h - 12)

        # Coluna 1: Nome e CPF / Assinatura (width ~200)
        col1_w = 190
        self.draw_text("Nome:", x + 4, y_box + 26, size=6, bold=True)
        self.draw_text("CPF:", x + 4, y_box + 8, size=6, bold=True)
        self.c.line(x + 90, y_box + 12, x + col1_w - 10, y_box + 12)
        self.draw_text_center("ASSINATURA/CARIMBO", x + 135, y_box + 4, size=5, bold=True)

        self.c.line(x + col1_w, y_box, x + col1_w, y_box + h - 12)

        # Coluna 2: Início e Término da Prestação (width ~130)
        col2_w = 120
        x_col2 = x + col1_w
        self.draw_text("INÍCIO DA PRESTAÇÃO - DATA / HORA", x_col2 + 4, y_box + 26, size=5.5, bold=True)
        self.draw_text("____/____/____     ___:___", x_col2 + 10, y_box + 18, size=6)
        self.draw_text("TÉRMINO DA PRESTAÇÃO - DATA / HORA", x_col2 + 4, y_box + 10, size=5.5, bold=True)
        self.draw_text("____/____/____     ___:___", x_col2 + 10, y_box + 2, size=6)

        self.c.line(x_col2 + col2_w, y_box, x_col2 + col2_w, y_box + h - 12)

        # Coluna 3: Nro Documento e Série (width ~140)
        col3_w = 135
        x_col3 = x_col2 + col2_w
        self.draw_text(f"NRO. DOCUMENTO: {self.data.get('nCT')}", x_col3 + 4, y_box + 26, size=6, bold=True)
        self.draw_text(f"SÉRIE: {self.data.get('serie')}", x_col3 + 4, y_box + 16, size=6, bold=True)
        filial_nome = (self.data.get("emit", {}).get("nome", "") or "")[:28]
        self.draw_text(f"FILIAL: {filial_nome}", x_col3 + 4, y_box + 6, size=5.5)

        # CT-E label destacada
        self.draw_text("CT-E", x_col3 + col3_w - 28, y_box + 25, size=8, bold=True)

        self.c.line(x_col3 + col3_w, y_box, x_col3 + col3_w, y_box + h - 12)

        # Coluna 4: Mini Barcode
        x_col4 = x_col3 + col3_w
        col4_w = w - (col1_w + col2_w + col3_w)
        key = self.data.get("key", "")
        if key and len(key) == 44:
            try:
                bc = createBarcodeDrawing(
                    "Code128",
                    value=key,
                    barWidth=0.8,
                    barHeight=24,
                    humanReadable=False,
                    quiet=False,
                )
                bc.drawOn(self.c, x_col4 + 4, y_box + 6)
            except Exception:
                pass

        # Linha pontilhada separando o canhoto
        self.y = y_box - 5
        self.c.saveState()
        self.c.setLineWidth(0.5)
        self.c.setDash(2, 2)
        self.c.line(x, self.y, x + w, self.y)
        self.c.restoreState()
        self.y -= 4

    def _render_cabecalho_dacte(self) -> None:
        h = 75
        y_box = self.y - h
        w = self.printable_width
        x = self.margin_x

        # Caixa do Emitente (Col 1: ~205pt)
        col1_w = 205
        self.draw_box(x, y_box, col1_w, h)

        emit = self.data.get("emit", {})
        self.draw_text(emit.get("nome", "TRANSPORTADORA"), x + 4, y_box + h - 11, size=7.5, bold=True)
        self.draw_text(emit.get("endereco", "-"), x + 4, y_box + h - 21, size=6)
        cidade_uf_cep = f"{emit.get('municipio', '')} - {emit.get('uf', '')} | CEP: {emit.get('cep', '')}"
        self.draw_text(cidade_uf_cep, x + 4, y_box + h - 30, size=6)
        if emit.get("fone"):
            self.draw_text(f"Fone: {emit.get('fone')}", x + 4, y_box + h - 39, size=6)

        self.draw_text(f"CNPJ: {emit.get('doc_fmt', '-')}", x + 4, y_box + 8, size=6.5, bold=True)
        self.draw_text(f"Ins.Est.: {emit.get('ie', '-')}", x + 115, y_box + 8, size=6.5, bold=True)

        # Caixa Central: DACTE e Identificação (Col 2: ~165pt)
        col2_w = 165
        x_col2 = x + col1_w
        self.draw_box(x_col2, y_box, col2_w, h)

        self.draw_text_center("DACTE", x_col2 + (col2_w / 2), y_box + h - 11, size=9, bold=True)
        self.draw_text_center("Doc. Auxiliar do Conhecimento de Transporte Eletrônico", x_col2 + (col2_w / 2), y_box + h - 20, size=5.5)

        # Modal destacado
        self.draw_box(x_col2 + 20, y_box + h - 38, col2_w - 40, 14, fill_color=colors.HexColor("#f1f3f4"))
        self.draw_text_center("Modal", x_col2 + (col2_w / 2), y_box + h - 30, size=5)
        self.draw_text_center(self.data.get("modal", "RODOVIÁRIO"), x_col2 + (col2_w / 2), y_box + h - 37, size=6.5, bold=True)

        # Grade Modelo / Série / Número / Data
        self.c.setLineWidth(0.4)
        self.c.line(x_col2, y_box + 22, x_col2 + col2_w, y_box + 22)
        grid_w = col2_w / 5
        self.draw_text_center("Modelo", x_col2 + (grid_w * 0.5), y_box + 16, size=5)
        self.draw_text_center("57", x_col2 + (grid_w * 0.5), y_box + 6, size=6.5, bold=True)
        self.c.line(x_col2 + grid_w, y_box, x_col2 + grid_w, y_box + 22)

        self.draw_text_center("Série", x_col2 + (grid_w * 1.5), y_box + 16, size=5)
        self.draw_text_center(self.data.get("serie", "1"), x_col2 + (grid_w * 1.5), y_box + 6, size=6.5, bold=True)
        self.c.line(x_col2 + (grid_w * 2), y_box, x_col2 + (grid_w * 2), y_box + 22)

        self.draw_text_center("Número", x_col2 + (grid_w * 2.8), y_box + 16, size=5)
        self.draw_text_center(self.data.get("nCT", "-"), x_col2 + (grid_w * 2.8), y_box + 6, size=6.5, bold=True)
        self.c.line(x_col2 + (grid_w * 3.6), y_box, x_col2 + (grid_w * 3.6), y_box + 22)

        self.draw_text_center("Data Emissão", x_col2 + (grid_w * 4.3), y_box + 16, size=5)
        self.draw_text_center(_format_date(self.data.get("dhEmi", "")), x_col2 + (grid_w * 4.3), y_box + 6, size=6, bold=True)

        # Caixa Direita: Código de Barras e Chave de Acesso (Col 3: ~185pt)
        col3_w = w - (col1_w + col2_w)
        x_col3 = x_col2 + col2_w
        self.draw_box(x_col3, y_box, col3_w, h)

        key = self.data.get("key", "")
        if key and len(key) == 44:
            try:
                bc = createBarcodeDrawing(
                    "Code128",
                    value=key,
                    barWidth=0.88,
                    barHeight=30,
                    humanReadable=False,
                    quiet=False,
                )
                bc.drawOn(self.c, x_col3 + 8, y_box + h - 38)
            except Exception:
                pass

        self.draw_text_center("Chave para consulta em www.cte.fazenda.gov.br ou Sefaz Autorizadora", x_col3 + (col3_w / 2), y_box + 27, size=4.8)
        self.draw_text_center(_format_key_grouped(key), x_col3 + (col3_w / 2), y_box + 18, size=6.2, bold=True)

        # Protocolo de Autorização
        self.c.setLineWidth(0.4)
        self.c.line(x_col3, y_box + 13, x_col3 + col3_w, y_box + 13)
        prot_str = f"{self.data.get('nProt', '-')} - {_format_datetime(self.data.get('dhRecbto', ''))}"
        self.draw_text("Protocolo de Autorização de Uso:", x_col3 + 4, y_box + 6, size=5)
        self.draw_text_right(prot_str, x_col3 + col3_w - 4, y_box + 6, size=5.5, bold=True)

        self.y = y_box

    def _render_tipo_cte_e_servico(self) -> None:
        h = 24
        y_box = self.y - h
        w = self.printable_width
        x = self.margin_x

        self.draw_box(x, y_box, w, h)

        # 4 colunas horizontais
        c_w = w / 4
        # Col 1: Tipo do CT-e
        self.draw_text("Tipo do CT-E", x + 4, y_box + 15, size=5.5)
        self.draw_text(self.data.get("tpCTe", "NORMAL"), x + 4, y_box + 5, size=6.5, bold=True)
        self.c.line(x + c_w, y_box, x + c_w, y_box + h)

        # Col 2: Tipo do Serviço
        self.draw_text("Tipo do Serviço", x + c_w + 4, y_box + 15, size=5.5)
        self.draw_text(self.data.get("tpServ", "NORMAL"), x + c_w + 4, y_box + 5, size=6.5, bold=True)
        self.c.line(x + (c_w * 2), y_box, x + (c_w * 2), y_box + h)

        # Col 3: Indicador CTe Globalizado
        self.draw_text("Indicador do CTe Globalizado", x + (c_w * 2) + 4, y_box + 15, size=5.5)
        self.draw_text(self.data.get("indGlobalizado", "N"), x + (c_w * 2) + 4, y_box + 5, size=6.5, bold=True)
        self.c.line(x + (c_w * 2.8), y_box, x + (c_w * 2.8), y_box + h)

        # Col 4: CFOP - Natureza da Prestação
        cfop_text = f"{self.data.get('cfop')} - {self.data.get('natOp')}"
        self.draw_text("CFOP - Natureza da Prestação", x + (c_w * 2.8) + 4, y_box + 15, size=5.5)
        self.draw_text(cfop_text[:50], x + (c_w * 2.8) + 4, y_box + 5, size=6, bold=True)

        self.y = y_box

    def _render_inicio_fim_prestacao(self) -> None:
        h = 18
        y_box = self.y - h
        w = self.printable_width
        x = self.margin_x

        self.draw_box(x, y_box, w, h)
        half_w = w / 2

        self.draw_text("Início da Prestação", x + 4, y_box + 11, size=5.5)
        ini_str = f"{self.data.get('xMunIni')} - {self.data.get('ufIni')}"
        self.draw_text(ini_str, x + 4, y_box + 3, size=6.5, bold=True)

        self.c.line(x + half_w, y_box, x + half_w, y_box + h)

        self.draw_text("Fim da Prestação", x + half_w + 4, y_box + 11, size=5.5)
        fim_str = f"{self.data.get('xMunFim')} - {self.data.get('ufFim')}"
        self.draw_text(fim_str, x + half_w + 4, y_box + 3, size=6.5, bold=True)

        self.y = y_box

    def _render_atores_transporte(self) -> None:
        """Renderiza Remetente, Destinatário, Expedidor, Recebedor e Tomador do Serviço."""
        w = self.printable_width
        x = self.margin_x
        half_w = w / 2

        # 1. Linha Remetente (esq) e Destinatário (dir)
        h_row1 = 46
        y_row1 = self.y - h_row1
        self.draw_box(x, y_row1, half_w, h_row1)
        self.draw_box(x + half_w, y_row1, half_w, h_row1)

        def _draw_actor(title: str, actor: dict[str, Any], bx: float, by: float, bw: float) -> None:
            self.draw_text(f"{title}: {actor.get('nome', '-')}", bx + 4, by + 37, size=6.5, bold=True)
            self.draw_text(f"Endereço: {actor.get('endereco', '-')}", bx + 4, by + 28, size=5.8)
            self.draw_text(f"Município: {actor.get('municipio', '-')}", bx + 4, by + 19, size=5.8)
            self.draw_text_right(f"CEP: {actor.get('cep', '-')}", bx + bw - 4, by + 19, size=5.8)
            self.draw_text(f"CNPJ/CPF: {actor.get('doc_fmt', '-')}", bx + 4, by + 10, size=5.8, bold=True)
            self.draw_text_right(f"Insc.Est.: {actor.get('ie', '-')}", bx + bw - 4, by + 10, size=5.8, bold=True)
            self.draw_text(f"UF: {actor.get('uf', '-')}   País: {actor.get('pais', 'BRASIL')}", bx + 4, by + 2, size=5.8)
            if actor.get("fone"):
                self.draw_text_right(f"Fone: {actor.get('fone')}", bx + bw - 4, by + 2, size=5.8)

        _draw_actor("Remetente", self.data.get("rem", {}), x, y_row1, half_w)
        _draw_actor("Destinatário", self.data.get("dest", {}), x + half_w, y_row1, half_w)
        self.y = y_row1

        # 2. Linha Expedidor (esq) e Recebedor (dir)
        h_row2 = 46
        y_row2 = self.y - h_row2
        self.draw_box(x, y_row2, half_w, h_row2)
        self.draw_box(x + half_w, y_row2, half_w, h_row2)

        exped = self.data.get("exped", {})
        if not exped:
            exped = {"nome": "-", "endereco": "-", "municipio": "-", "cep": "-", "doc_fmt": "-", "ie": "-", "uf": "-", "pais": "-"}
        receb = self.data.get("receb", {})
        if not receb:
            receb = {"nome": "-", "endereco": "-", "municipio": "-", "cep": "-", "doc_fmt": "-", "ie": "-", "uf": "-", "pais": "-"}

        _draw_actor("Expedidor", exped, x, y_row2, half_w)
        _draw_actor("Recebedor", receb, x + half_w, y_row2, half_w)
        self.y = y_row2

        # 3. Tomador do Serviço (largura total)
        h_toma = 24
        y_toma = self.y - h_toma
        self.draw_box(x, y_toma, w, h_toma)

        toma = self.data.get("tomador", {})
        toma_tipo = self.data.get("tomador_tipo", "REMETENTE")
        self.draw_text(f"Tomador Serviço: {toma_tipo} - {toma.get('nome', '-')}", x + 4, y_toma + 15, size=6.2, bold=True)
        self.draw_text(f"Endereço: {toma.get('endereco', '-')}", x + 4, y_toma + 5, size=5.8)
        self.draw_text(f"Município: {toma.get('municipio', '-')} - {toma.get('uf', '-')}", x + 280, y_toma + 15, size=5.8)
        self.draw_text(f"CNPJ/CPF: {toma.get('doc_fmt', '-')}", x + 280, y_toma + 5, size=5.8, bold=True)
        self.draw_text_right(f"CEP: {toma.get('cep', '-')}", x + w - 4, y_toma + 15, size=5.8)
        self.draw_text_right(f"Insc.Est.: {toma.get('ie', '-')}", x + w - 4, y_toma + 5, size=5.8)

        self.y = y_toma

    def _render_dados_carga_e_seguro(self) -> None:
        h = 36
        y_box = self.y - h
        w = self.printable_width
        x = self.margin_x

        self.draw_box(x, y_box, w, h)

        # Linha 1: Produto predominante, outras características e valor da mercadoria
        self.draw_text("PRODUTO PREDOMINANTE", x + 4, y_box + 27, size=5)
        self.draw_text(self.data.get("proPred", "-")[:35], x + 4, y_box + 19, size=6, bold=True)
        self.c.line(x + 190, y_box + 17, x + 190, y_box + h)

        self.draw_text("OUTRAS CARACTERÍSTICAS DA CARGA", x + 194, y_box + 27, size=5)
        self.draw_text(self.data.get("xOutCat", "-")[:35], x + 194, y_box + 19, size=6, bold=True)
        self.c.line(x + 390, y_box + 17, x + 390, y_box + h)

        self.draw_text("VALOR DA MERCADORIA", x + 394, y_box + 27, size=5)
        self.draw_text_right(f"R$ {self.data.get('vCarga', '0,00')}", x + w - 4, y_box + 19, size=6.5, bold=True)

        self.c.line(x, y_box + 17, x + w, y_box + 17)

        # Linha 2: Quantidade de carga & Seguro
        # Medidas (KG, etc.)
        qtds = self.data.get("quantidades", [])
        qtd_text = " / ".join([f"{q.get('unidade')}: {q.get('qtd')}" for q in qtds]) if qtds else "-"
        self.draw_text("QTD. CARGA:", x + 4, y_box + 5, size=5.5, bold=True)
        self.draw_text(qtd_text[:40], x + 45, y_box + 5, size=6)
        self.c.line(x + 190, y_box, x + 190, y_box + 17)

        seg = self.data.get("seguro", {})
        seg_text = f"SEGURADORA: {seg.get('seguradora', '-')} | APÓLICE: {seg.get('apolice', '-')} | VALOR AVERB.: R$ {seg.get('v_aver', '0,00')}"
        self.draw_text(seg_text[:85], x + 194, y_box + 5, size=5.5)

        self.y = y_box

    def _render_componentes_prestacao(self) -> None:
        h = 42
        y_box = self.y - h
        w = self.printable_width
        x = self.margin_x

        self.draw_box(x, y_box, w, h)

        # Cabeçalho da seção
        self.draw_box(x, y_box + h - 10, w, 10, fill_color=colors.HexColor("#f8f9fa"))
        self.draw_text_center("COMPONENTES DA PRESTAÇÃO DO SERVIÇO", x + (w / 2), y_box + h - 7, size=6, bold=True)

        comps = self.data.get("componentes", [])
        x_col = x + 4
        y_c = y_box + h - 18

        # Renderiza até 6 componentes em 3 colunas
        comp_area_w = w - 140
        col_w = comp_area_w / 3

        for i, c in enumerate(comps[:6]):
            col_idx = i % 3
            row_idx = i // 3
            cx = x + 4 + (col_idx * col_w)
            cy = y_box + 16 - (row_idx * 9)

            self.draw_text(f"{c.get('nome')}:", cx, cy, size=5.5)
            self.draw_text_right(f"R$ {c.get('valor')}", cx + col_w - 8, cy, size=5.5, bold=True)

        # Divisória do totalizador à direita
        self.c.line(x + comp_area_w, y_box, x + comp_area_w, y_box + h - 10)

        x_tot = x + comp_area_w
        self.draw_text("VALOR TOTAL DO SERVIÇO", x_tot + 4, y_box + 22, size=5, bold=True)
        self.draw_text_right(f"R$ {self.data.get('vTPrest', '0,00')}", x + w - 4, y_box + 22, size=7, bold=True)

        self.c.line(x_tot, y_box + 15, x + w, y_box + 15)

        self.draw_text("VALOR A RECEBER", x_tot + 4, y_box + 5, size=5, bold=True)
        self.draw_text_right(f"R$ {self.data.get('vRec', '0,00')}", x + w - 4, y_box + 5, size=7.5, bold=True)

        self.y = y_box

    def _render_informacoes_imposto(self) -> None:
        h = 28
        y_box = self.y - h
        w = self.printable_width
        x = self.margin_x

        self.draw_box(x, y_box, w, h)

        # Cabeçalho da seção
        self.draw_box(x, y_box + h - 10, w, 10, fill_color=colors.HexColor("#f8f9fa"))
        self.draw_text_center("INFORMAÇÕES RELATIVAS AO IMPOSTO", x + (w / 2), y_box + h - 7, size=6, bold=True)

        # 6 campos
        cols_w = [155, 75, 85, 75, 85, 80]
        cur_x = x
        headers = [
            ("SITUAÇÃO TRIBUTÁRIA", self.data.get("cst_desc", "-")),
            ("% RED. BC", self.data.get("pRedBC", "0,00")),
            ("BASE CÁLCULO", f"R$ {self.data.get('vBC', '0,00')}"),
            ("ALÍQ. ICMS", f"{self.data.get('pICMS', '0,00')} %"),
            ("VALOR ICMS", f"R$ {self.data.get('vICMS', '0,00')}"),
            ("VL. CRÉDITO", f"R$ {self.data.get('vCred', '0,00')}"),
        ]

        for i, (title, val) in enumerate(headers):
            bw = cols_w[i]
            if i > 0:
                self.c.line(cur_x, y_box, cur_x, y_box + h - 10)
            self.draw_text(title, cur_x + 3, y_box + 10, size=5)
            self.draw_text(str(val), cur_x + 3, y_box + 2, size=6, bold=True)
            cur_x += bw

        self.y = y_box

    def _render_documentos_originarios(self) -> None:
        docs = self.data.get("docs_originarios", [])
        num_docs = max(1, min(len(docs), 3))
        h = 13 + (num_docs * 10)
        y_box = self.y - h
        w = self.printable_width
        x = self.margin_x

        self.draw_box(x, y_box, w, h)

        # Cabeçalho da seção
        self.draw_box(x, y_box + h - 10, w, 10, fill_color=colors.HexColor("#f8f9fa"))
        self.draw_text_center("DOCUMENTOS ORIGINÁRIOS", x + (w / 2), y_box + h - 7, size=6, bold=True)

        # Cabeçalho de colunas
        y_row = y_box + h - 18
        self.draw_text("TIPO DOC", x + 4, y_row, size=5, bold=True)
        self.draw_text("CNPJ/CPF EMITENTE", x + 50, y_row, size=5, bold=True)
        self.draw_text("SÉRIE/NR. DOCUMENTO", x + 150, y_row, size=5, bold=True)
        self.draw_text("CHAVE DE ACESSO DA NF-E", x + 250, y_row, size=5, bold=True)

        if not docs:
            self.draw_text("Nenhum documento originário informado", x + 4, y_row - 9, size=5.5)
        else:
            for i, doc in enumerate(docs[:3]):
                dr_y = y_row - 9 - (i * 9)
                self.draw_text(doc.get("tipo", "NFE"), x + 4, dr_y, size=5.5)
                self.draw_text(doc.get("doc_emit", "-"), x + 50, dr_y, size=5.5)
                self.draw_text(doc.get("serie_num", "-"), x + 150, dr_y, size=5.5)
                self.draw_text(doc.get("chave", "-"), x + 250, dr_y, size=5.5, bold=True)

        self.y = y_box

    def _render_observacoes(self) -> None:
        h = 36
        y_box = self.y - h
        w = self.printable_width
        x = self.margin_x

        self.draw_box(x, y_box, w, h)

        # Cabeçalho da seção
        self.draw_box(x, y_box + h - 9, w, 9, fill_color=colors.HexColor("#f8f9fa"))
        self.draw_text_center("OBSERVAÇÕES", x + (w / 2), y_box + h - 6.5, size=5.5, bold=True)

        # Renderiza veículos/motoristas se houver
        veic_str = ""
        veics = self.data.get("veiculos", [])
        if veics:
            veic_str = f"Veículo(s): {', '.join([f'Placa {v.get('placa')} ({v.get('uf')})' for v in veics])}. "

        moto_str = ""
        motos = self.data.get("motoristas", [])
        if motos:
            moto_str = f"Motorista(s): {', '.join([f'{m.get('nome')} ({m.get('cpf')})' for m in motos])}. "

        obs = f"{veic_str}{moto_str}{self.data.get('observacoes', '-')}".strip()

        # Quebra em 3 linhas
        line_len = 135
        self.draw_text(obs[:line_len], x + 4, y_box + 18, size=5.2)
        if len(obs) > line_len:
            self.draw_text(obs[line_len:line_len*2], x + 4, y_box + 10, size=5.2)
        if len(obs) > line_len * 2:
            self.draw_text(obs[line_len*2:line_len*3], x + 4, y_box + 2, size=5.2)

        self.y = y_box

    def _render_rodape(self) -> None:
        h = 32
        y_box = self.y - h
        w = self.printable_width
        x = self.margin_x

        self.draw_box(x, y_box, w, h)

        col1_w = 170
        col2_w = 120
        col3_w = w - (col1_w + col2_w)

        # Coluna 1: RNTRC
        self.draw_text("RNTRC DA EMPRESA", x + 4, y_box + 23, size=5, bold=True)
        self.draw_text(self.data.get("rntrc", "-"), x + 4, y_box + 13, size=6, bold=True)
        self.c.line(x + col1_w, y_box, x + col1_w, y_box + h)

        # Coluna 2: Data prevista entrega
        x_col2 = x + col1_w
        self.draw_text("DATA PREVISTA DE ENTREGA", x_col2 + 4, y_box + 23, size=5, bold=True)
        self.draw_text(_format_date(self.data.get("dhEmi", "")), x_col2 + 4, y_box + 13, size=6)
        self.c.line(x_col2 + col2_w, y_box, x_col2 + col2_w, y_box + h)

        # Coluna 3: Reservado ao fisco / Uso exclusivo do emissor
        x_col3 = x_col2 + col2_w
        self.draw_text("RESERVADO AO FISCO", x_col3 + 4, y_box + 23, size=5, bold=True)
        self.draw_text("USO EXCLUSIVO DO EMISSOR DO CT-e", x + 4, y_box + 4, size=4.8, bold=True)
        self.draw_text_right("DACTE impresso via Cliente Autônomo Python SEFAZ DF-e", x + w - 4, y_box + 4, size=4.8)

        self.y = y_box


def generate_dacte_pdf(
    xml_input: str | Path,
    output_pdf_path: str | Path | None = None,
) -> Path:
    """
    Gera o DACTE (Conhecimento de Transporte Eletrônico) em PDF a partir do XML.
    """
    if isinstance(xml_input, (str, Path)) and os.path.exists(str(xml_input)):
        p = Path(xml_input)
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = p.read_text(encoding="latin-1")
    else:
        content = str(xml_input)

    data = extract_dacte_data(content)

    if output_pdf_path is None:
        key = data.get("key") or f"cte_{data.get('nCT')}"
        default_dir = Path(__file__).resolve().parent.parent.parent / "sefaz_data" / "danfes"
        default_dir.mkdir(parents=True, exist_ok=True)
        output_pdf_path = default_dir / f"DACTE_{key}.pdf"
    else:
        output_pdf_path = Path(output_pdf_path)

    renderer = DactePdfRenderer(data, output_pdf_path)
    return renderer.render()

