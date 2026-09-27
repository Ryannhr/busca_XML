"""
Processador de Operações em Lote:
1. Consulta e Download em Lote na SEFAZ com controle de fila e cota.
2. Auditoria e Validação em Lote de Pastas com arquivos XML.
"""

import csv
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .registry import SefazLocalRegistry
from .rules import validate_nfe_access_key
from .soap_client import execute_sefaz_nsu_query, execute_sefaz_query, strip_xml_namespaces
from .xml_validator import inspect_and_validate_xml, validate_xml_file


def extract_keys_from_text(raw_text: str) -> list[str]:
    """
    Extrai e higieniza chaves de acesso de 44 dígitos a partir de texto bruto,
    linhas de arquivo, planilhas CSV ou colagens.
    """
    keys = []
    seen = set()
    lines = raw_text.splitlines()

    for line in lines:
        cleaned = re.sub(r"\D", "", line)
        # Se a linha contiver exatamente 44 dígitos ou contiver uma sequência de 44 dígitos
        matches = re.findall(r"\b\d{44}\b", cleaned)
        if not matches and len(cleaned) == 44:
            matches = [cleaned]

        for k in matches:
            if k not in seen:
                seen.add(k)
                keys.append(k)

    return keys


def extract_keys_from_file(file_path: str | Path) -> list[str]:
    """Lê um arquivo TXT ou CSV e extrai todas as chaves de 44 dígitos encontradas."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")

    try:
        content = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = p.read_text(encoding="latin-1")

    return extract_keys_from_text(content)


@dataclass
class BatchQueryItem:
    """Representa o estado de uma chave dentro da fila de consulta em lote."""
    access_key: str
    status: str  # "PENDENTE", "EM_CACHE", "VALIDANDO", "BAIXANDO", "CONCLUIDO", "ERRO", "BLOQUEADO"
    source: str  # "CACHE_LOCAL", "SEFAZ_SVRS", "FALHA_VALIDACAO", "-"
    message: str = ""
    file_path: str | None = None
    c_stat: int | None = None


class BatchQueryManager:
    """
    Gerenciador da fila de consulta e download em lote na SEFAZ.
    Garante respeito estrito à cota horária para prevenir cStat 656.
    """

    def __init__(
        self,
        registry: SefazLocalRegistry,
        cnpj: str,
        cert_path: str | Path,
        cert_password: str,
        is_homologation: bool = False,
        delay_between_queries: float = 2.0,
    ):
        self.registry = registry
        self.cnpj = cnpj
        self.cert_path = cert_path
        self.cert_password = cert_password
        self.is_homologation = is_homologation
        self.delay_between_queries = delay_between_queries
        self.items: list[BatchQueryItem] = []
        self._stop_requested = False

    def load_keys(self, keys: list[str]) -> list[BatchQueryItem]:
        """Carrega a lista de chaves e executa a pré-classificação (cache e regras)."""
        self.items = []
        self._stop_requested = False

        for key in keys:
            # 1. Validação prévia
            val = validate_nfe_access_key(key)
            if not val.valid:
                self.items.append(BatchQueryItem(
                    access_key=key,
                    status="ERRO",
                    source="FALHA_VALIDACAO",
                    message=f"Chave inválida: {', '.join(val.errors)}",
                ))
                continue

            clean_key = val.normalized

            # 2. Verificação de Cache Local
            cached_file = self.registry.get_cached_xml(clean_key)
            if cached_file:
                self.items.append(BatchQueryItem(
                    access_key=clean_key,
                    status="EM_CACHE",
                    source="CACHE_LOCAL",
                    message="Documento já disponível no cache local (zero consultas à SEFAZ)",
                    file_path=str(cached_file),
                    c_stat=138,
                ))
            else:
                self.items.append(BatchQueryItem(
                    access_key=clean_key,
                    status="PENDENTE",
                    source="-",
                    message="Aguardando transmissão para a SEFAZ",
                ))

        return self.items

    def reset_paused_or_blocked(self) -> int:
        """
        Restaura itens com status PAUSADO ou BLOQUEADO de volta para PENDENTE,
        permitindo que a esteira continue exatamente de onde parou.
        Retorna a quantidade de itens reativados.
        """
        reactivated = 0
        for it in self.items:
            if it.status in ("PAUSADO", "BLOQUEADO"):
                # Verifica antes se o XML já foi baixado entretanto
                cached = self.registry.get_cached_xml(it.access_key)
                if cached:
                    it.status = "EM_CACHE"
                    it.source = "CACHE_LOCAL"
                    it.message = "Documento já disponível no cache local (zero consultas à SEFAZ)"
                    it.file_path = str(cached)
                else:
                    it.status = "PENDENTE"
                    it.message = "Aguardando transmissão para a SEFAZ"
                    reactivated += 1
        return reactivated

    def stop(self) -> None:
        """Solicita a interrupção graciosa do processamento em lote."""
        self._stop_requested = True

    def process(
        self,
        on_item_updated: Callable[[int, BatchQueryItem], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        auto_wait_quota: bool = False,
        on_waiting: Callable[[int, str], None] | None = None,
    ) -> dict[str, Any]:
        """
        Executa a fila de consultas pendentes.
        Se auto_wait_quota=True, aguarda automaticamente a liberação de cota
        da SEFAZ (janela de 1h ou travas temporárias) e continua sozinho sem parar.
        """
        self._stop_requested = False
        total = len(self.items)
        cache_hits = sum(1 for it in self.items if it.status == "EM_CACHE")
        downloaded = 0
        errors = sum(1 for it in self.items if it.status == "ERRO")
        skipped_rate_limit = 0

        # Validação Prévia do Certificado antes de gastar qualquer requisição
        pending_count = sum(1 for it in self.items if it.status == "PENDENTE")
        if pending_count > 0:
            from .certificate import inspect_certificate
            try:
                cert_info = inspect_certificate(self.cert_path, self.cert_password)
                if cert_info["is_expired"]:
                    for idx, it in enumerate(self.items):
                        if it.status == "PENDENTE":
                            it.status = "ERRO"
                            it.message = f"Certificado A1 EXPIRADO desde {cert_info['valid_until']}"
                            errors += 1
                            if on_item_updated:
                                on_item_updated(idx, it)
                    return {
                        "total": total,
                        "cache_hits": cache_hits,
                        "downloaded": 0,
                        "errors": errors,
                        "rate_limited": 0,
                        "stopped": True,
                        "error_message": f"Certificado Digital A1 ({cert_info['subject_cn']}) expirado desde {cert_info['valid_until']}.",
                    }
            except Exception as e:
                for idx, it in enumerate(self.items):
                    if it.status == "PENDENTE":
                        it.status = "ERRO"
                        it.message = f"Falha no certificado: {e}"
                        errors += 1
                        if on_item_updated:
                            on_item_updated(idx, it)
                return {
                    "total": total,
                    "cache_hits": cache_hits,
                    "downloaded": 0,
                    "errors": errors,
                    "rate_limited": 0,
                    "stopped": True,
                    "error_message": f"Falha no Certificado Digital: {e}",
                }

        for index, item in enumerate(self.items):
            if self._stop_requested:
                if item.status in ("PENDENTE", "AGUARDANDO_COTA"):
                    item.status = "PAUSADO"
                    item.message = "Processamento interrompido pelo usuário."
                    if on_item_updated:
                        on_item_updated(index, item)
                continue

            if item.status != "PENDENTE":
                if on_progress:
                    on_progress(index + 1, total)
                continue

            # Verifica limites de taxa e travas da SEFAZ
            allowed, block_msg = self.registry.check_rate_limit()
            if not allowed:
                if auto_wait_quota and not self._stop_requested:
                    item.status = "AGUARDANDO_COTA"
                    if on_item_updated:
                        on_item_updated(index, item)

                    # Entra em espera ativa fracionada (1s) para permitir parada a qualquer instante
                    while not self._stop_requested:
                        wait_sec = self.registry.get_seconds_until_next_slot()
                        if wait_sec <= 0:
                            allowed_check, _ = self.registry.check_rate_limit()
                            if allowed_check:
                                break

                        mins = wait_sec // 60
                        secs = wait_sec % 60
                        time_display = f"{mins:02d}:{secs:02d}"
                        info_msg = f"Cota horária atingida (15/15). Próxima liberação em {time_display} min (Auto-Retomada Ativa)..."
                        item.message = info_msg
                        if on_item_updated:
                            on_item_updated(index, item)
                        if on_waiting:
                            on_waiting(wait_sec, info_msg)

                        time.sleep(1)

                    if self._stop_requested:
                        item.status = "PAUSADO"
                        item.message = "Processamento interrompido pelo usuário."
                        if on_item_updated:
                            on_item_updated(index, item)
                        continue

                    # Cota liberada: volta para PENDENTE e executa normalmente
                    item.status = "PENDENTE"
                    if on_waiting:
                        on_waiting(0, "Cota liberada! Retomando consultas automaticamente...")
                else:
                    item.status = "BLOQUEADO"
                    item.message = f"Pausado por segurança fiscal: {block_msg}"
                    skipped_rate_limit += 1
                    if on_item_updated:
                        on_item_updated(index, item)
                    if on_progress:
                        on_progress(index + 1, total)
                    self._stop_requested = True
                    continue

            item.status = "BAIXANDO"
            item.message = "Enviando requisição SOAP 1.2 mTLS à SEFAZ..."
            if on_item_updated:
                on_item_updated(index, item)

            self.registry.register_query_attempt(access_key=item.access_key, cnpj=self.cnpj)

            try:
                resp = execute_sefaz_query(
                    access_key=item.access_key,
                    cnpj=self.cnpj,
                    cert_path=self.cert_path,
                    cert_password=self.cert_password,
                    is_homologation=self.is_homologation,
                )
                self.registry.register_directive(resp.directive)

                item.c_stat = resp.c_stat
                if resp.c_stat == 138 and resp.documents:
                    for doc in resp.documents:
                        fp = self.registry.store_xml(item.access_key, doc["xml"], c_stat=resp.c_stat)
                        item.file_path = str(fp)
                    item.status = "CONCLUIDO"
                    item.source = "SEFAZ_SVRS"
                    item.message = f"XML baixado com sucesso! (cStat 138 - {resp.x_motivo})"
                    downloaded += 1
                else:
                    item.status = "ERRO"
                    item.source = "SEFAZ_SVRS"
                    item.message = f"SEFAZ cStat {resp.c_stat}: {resp.x_motivo} ({resp.directive.reason})"
                    errors += 1

                    # Se a SEFAZ retornou trava (137 ou 656)
                    if resp.directive.action in ("WAIT", "BLOCK"):
                        if auto_wait_quota and not self._stop_requested:
                            item.status = "PENDENTE"
                            item.message = f"SEFAZ solicitou espera ({resp.directive.reason}). Aguardando liberação..."
                        else:
                            self._stop_requested = True

            except Exception as e:
                item.status = "ERRO"
                item.message = f"Falha na comunicação: {e}"
                errors += 1

            if on_item_updated:
                on_item_updated(index, item)
            if on_progress:
                on_progress(index + 1, total)

            # Intervalo respeitoso entre chamadas externas
            if not self._stop_requested and self.delay_between_queries > 0:
                time.sleep(self.delay_between_queries)

        return {
            "total": total,
            "cache_hits": cache_hits,
            "downloaded": downloaded,
            "errors": errors,
            "rate_limited": skipped_rate_limit,
            "stopped": self._stop_requested,
        }


@dataclass
class BatchXmlAuditRow:
    """Linha consolidada de auditoria de um arquivo XML da pasta."""
    file_name: str
    file_path: str
    status: str  # "VÁLIDO", "ALERTA", "ERRO"
    doc_type: str
    access_key: str
    nfe_number: str
    series: str
    issue_date: str
    emit_doc: str
    emit_name: str
    dest_doc: str
    dest_name: str
    total_value: str
    protocol_num: str
    cstat_auth: str
    has_signature: str
    diagnostics: str


class BatchFolderValidator:
    """
    Auditor em lote de diretórios contendo arquivos XML de NF-e e DF-e.
    """

    @staticmethod
    def scan_and_validate_directory(
        dir_path: str | Path,
        recursive: bool = False,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> list[BatchXmlAuditRow]:
        folder = Path(dir_path)
        if not folder.exists() or not folder.is_dir():
            raise NotADirectoryError(f"Diretório inválido: {dir_path}")

        pattern = "**/*.xml" if recursive else "*.xml"
        xml_files = list(folder.glob(pattern))
        total = len(xml_files)
        results: list[BatchXmlAuditRow] = []

        for index, fp in enumerate(xml_files):
            if on_progress:
                on_progress(index + 1, total, fp.name)

            report = validate_xml_file(fp)

            # Classifica status geral
            if not report.is_valid_syntax or (report.access_key and not report.is_valid_key):
                row_status = "ERRO"
            elif any(m["level"] == "WARN" for m in report.messages):
                row_status = "ALERTA"
            else:
                row_status = "VÁLIDO"

            nd = report.nfe_data
            auth = report.authorization_data

            diag_text = " | ".join([f"[{m['level']}] {m['text']}" for m in report.messages[:3]])

            results.append(BatchXmlAuditRow(
                file_name=fp.name,
                file_path=str(fp.resolve()),
                status=row_status,
                doc_type=f"<{report.doc_type}>",
                access_key=report.access_key or "-",
                nfe_number=nd.get("nNF", "-"),
                series=nd.get("serie", "-"),
                issue_date=nd.get("dhEmi", "-"),
                emit_doc=nd.get("emit_doc", "-"),
                emit_name=nd.get("emit_nome", "-"),
                dest_doc=nd.get("dest_doc", "-"),
                dest_name=nd.get("dest_nome", "-"),
                total_value=nd.get("vNF", "0.00"),
                protocol_num=auth.get("nProt", "-"),
                cstat_auth=auth.get("cStat", "-"),
                has_signature="SIM" if report.signature_found else "NÃO",
                diagnostics=diag_text,
            ))

        return results

    @staticmethod
    def export_to_csv(rows: list[BatchXmlAuditRow], output_path: str | Path) -> Path:
        """
        Exporta os resultados consolidados para arquivo CSV no padrão brasileiro
        (ponto-e-vírgula e UTF-8 com BOM para abrir diretamente no Excel).
        """
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "Arquivo",
            "Status",
            "Tipo Documento",
            "Chave de Acesso",
            "Número NF-e",
            "Série",
            "Data Emissão",
            "CNPJ/CPF Emitente",
            "Razão Social Emitente",
            "CNPJ/CPF Destinatário",
            "Razão Social Destinatário",
            "Valor Total (R$)",
            "Protocolo SEFAZ",
            "cStat Autorização",
            "Assinatura Digital",
            "Diagnósticos",
            "Caminho do Arquivo",
        ]

        with open(p, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(fieldnames)

            for r in rows:
                writer.writerow([
                    r.file_name,
                    r.status,
                    r.doc_type,
                    r.access_key,
                    r.nfe_number,
                    r.series,
                    r.issue_date,
                    r.emit_doc,
                    r.emit_name,
                    r.dest_doc,
                    r.dest_name,
                    r.total_value.replace(".", ","),
                    r.protocol_num,
                    r.cstat_auth,
                    r.has_signature,
                    r.diagnostics,
                    r.file_path,
                ])

        return p

    @staticmethod
    def generate_danfes_for_rows(
        rows: list[BatchXmlAuditRow],
        output_directory: str | Path,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> dict:
        """
        Converte todos os XMLs válidos (ou com alertas) da auditoria em arquivos DANFE (NF-e) ou DACTE (CT-e) em PDF.
        Retorna relatório de execução com total gerado, erros e caminhos.
        """
        from .danfe_generator import detect_document_type, generate_fiscal_document_pdf
        out_dir = Path(output_directory)
        out_dir.mkdir(parents=True, exist_ok=True)

        generated = []
        errors = []
        candidates = [r for r in rows if r.status in ("VÁLIDO", "ALERTA") and Path(r.file_path).exists()]
        total = len(candidates)

        for i, row in enumerate(candidates):
            fp = Path(row.file_path)
            try:
                try:
                    xml_content = fp.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    xml_content = fp.read_text(encoding="latin-1")

                doc_type = detect_document_type(row.access_key if (row.access_key and row.access_key != "-") else xml_content)
                prefix = "DACTE" if doc_type == "CTE" else "DANFE"
                key_part = row.access_key if (row.access_key and row.access_key != "-") else fp.stem
                pdf_filename = f"{prefix}_{key_part}.pdf"
                dest_path = out_dir / pdf_filename

                _, out_pdf = generate_fiscal_document_pdf(xml_content, output_pdf_path=dest_path)
                generated.append(str(out_pdf.resolve()))
                if on_progress:
                    on_progress(i + 1, total, pdf_filename)
            except Exception as e:
                errors.append({"file": row.file_name, "error": str(e)})

        return {
            "total_candidates": total,
            "generated_count": len(generated),
            "error_count": len(errors),
            "generated_files": generated,
            "errors": errors,
            "output_directory": str(out_dir.resolve()),
        }


@dataclass
class NsuDocumentItem:
    """Representa um documento fiscal retornado em lote pelo WebService distNSU."""
    nsu: str
    schema: str
    doc_type: str
    access_key: str
    nfe_number: str
    series: str
    emit_name: str
    emit_doc: str
    total_value: str
    issue_date: str
    xml_content: str
    file_path: str = ""
    status: str = "BAIXADO"


def parse_nsu_doc_xml(schema: str, nsu: str, xml_content: str) -> NsuDocumentItem:
    """
    Decodifica o conteúdo XML de um <docZip> da SEFAZ e extrai seus metadados fiscais.
    """
    clean = strip_xml_namespaces(xml_content.strip())
    try:
        root = ET.fromstring(clean)
    except Exception:
        return NsuDocumentItem(
            nsu=nsu,
            schema=schema,
            doc_type="XML Inválido",
            access_key="-",
            nfe_number="-",
            series="-",
            emit_name="-",
            emit_doc="-",
            total_value="0.00",
            issue_date="-",
            xml_content=xml_content,
            status="ERRO_SINTAXE",
        )

    # 1. NF-e completa (procNFe ou infNFe)
    inf_nfe = root.find(".//infNFe")
    if inf_nfe is not None:
        raw_id = inf_nfe.attrib.get("Id", "")
        key = re.sub(r"\D", "", raw_id)
        ide = inf_nfe.find("ide")
        emit = inf_nfe.find("emit")
        total = inf_nfe.find(".//total/ICMSTot")

        emit_doc = "-"
        if emit is not None:
            emit_doc = emit.findtext("CNPJ") or emit.findtext("CPF", "-")
        return NsuDocumentItem(
            nsu=nsu,
            schema=schema,
            doc_type="NF-e (Completa)",
            access_key=key,
            nfe_number=ide.findtext("nNF", "-") if ide is not None else "-",
            series=ide.findtext("serie", "-") if ide is not None else "-",
            emit_name=emit.findtext("xNome", "-") if emit is not None else "-",
            emit_doc=emit_doc,
            total_value=total.findtext("vNF", "0.00") if total is not None else "0.00",
            issue_date=(ide.findtext("dhEmi") or ide.findtext("dEmi", "-")) if ide is not None else "-",
            xml_content=xml_content,
        )

    # 2. CT-e completo (procCTe ou infCte)
    inf_cte = root.find(".//infCte")
    if inf_cte is not None:
        raw_id = inf_cte.attrib.get("Id", "")
        key = re.sub(r"\D", "", raw_id)
        ide = inf_cte.find("ide")
        emit = inf_cte.find("emit")
        v_prest = inf_cte.find("vPrest")

        emit_doc = "-"
        if emit is not None:
            emit_doc = emit.findtext("CNPJ") or emit.findtext("CPF", "-")
        return NsuDocumentItem(
            nsu=nsu,
            schema=schema,
            doc_type="CT-e (Completo)",
            access_key=key,
            nfe_number=ide.findtext("nCT", "-") if ide is not None else "-",
            series=ide.findtext("serie", "-") if ide is not None else "-",
            emit_name=emit.findtext("xNome", "-") if emit is not None else "-",
            emit_doc=emit_doc,
            total_value=v_prest.findtext("vTPrest", "0.00") if v_prest is not None else "0.00",
            issue_date=ide.findtext("dhEmi", "-") if ide is not None else "-",
            xml_content=xml_content,
        )

    # 3. Resumo de NF-e (resNFe)
    res_nfe = root if root.tag == "resNFe" else root.find(".//resNFe")
    if res_nfe is not None:
        key = res_nfe.findtext("chNFe", "-")
        doc_val = res_nfe.findtext("CNPJ") or res_nfe.findtext("CPF", "-")
        nfe_num = "-"
        serie_num = "-"
        if len(key) == 44:
            if key[25:34].isdigit():
                nfe_num = str(int(key[25:34]))
            if key[22:25].isdigit():
                serie_num = str(int(key[22:25]))
        return NsuDocumentItem(
            nsu=nsu,
            schema=schema,
            doc_type="Resumo NF-e",
            access_key=key,
            nfe_number=nfe_num,
            series=serie_num,
            emit_name=res_nfe.findtext("xNome", "-"),
            emit_doc=doc_val,
            total_value=res_nfe.findtext("vNF", "0.00"),
            issue_date=res_nfe.findtext("dhEmi", "-"),
            xml_content=xml_content,
        )

    # 4. Resumo de CT-e (resCTe)
    res_cte = root if root.tag == "resCTe" else root.find(".//resCTe")
    if res_cte is not None:
        key = res_cte.findtext("chCTe", "-")
        doc_val = res_cte.findtext("CNPJ") or res_cte.findtext("CPF", "-")
        cte_num = "-"
        serie_num = "-"
        if len(key) == 44:
            if key[25:34].isdigit():
                cte_num = str(int(key[25:34]))
            if key[22:25].isdigit():
                serie_num = str(int(key[22:25]))
        return NsuDocumentItem(
            nsu=nsu,
            schema=schema,
            doc_type="Resumo CT-e",
            access_key=key,
            nfe_number=cte_num,
            series=serie_num,
            emit_name=res_cte.findtext("xNome", "-"),
            emit_doc=doc_val,
            total_value=res_cte.findtext("vTPrest", "0.00"),
            issue_date=res_cte.findtext("dhEmi", "-"),
            xml_content=xml_content,
        )

    # 5. Evento (procEventoNFe ou resEvento)
    evento = root.find(".//infEvento")
    if evento is None:
        evento = root.find(".//resEvento")
    if evento is None:
        evento = root

    ch_doc = root.findtext(".//chNFe") or root.findtext(".//chCTe", "-")
    tp_ev = evento.findtext("xEvento") or evento.findtext("tpEvento", "Evento")
    return NsuDocumentItem(
        nsu=nsu,
        schema=schema,
        doc_type=f"Evento ({tp_ev[:18]})",
        access_key=ch_doc,
        nfe_number="-",
        series="-",
        emit_name=evento.findtext("CNPJ", "-"),
        emit_doc=evento.findtext("CNPJ", "-"),
        total_value="0.00",
        issue_date=evento.findtext("dhEvento", "-"),
        xml_content=xml_content,
    )


class NsuSyncManager:
    """
    Gerenciador de sincronização em lote oficial por NSU (distNSU).
    Recupera pacotes de até 50 documentos por chamada e itera continuamente
    até que ultNSU atinja maxNSU ou a SEFAZ retorne cStat 137.
    """
    def __init__(
        self,
        registry: SefazLocalRegistry,
        cnpj: str,
        cert_path: str | Path,
        cert_password: str,
        c_uf_autor: str = "35",
        is_homologation: bool = False,
        delay_seconds: float = 1.5,
    ):
        self.registry = registry
        self.cnpj = cnpj
        self.cert_path = cert_path
        self.cert_password = cert_password
        self.c_uf_autor = c_uf_autor
        self.is_homologation = is_homologation
        self.delay_seconds = delay_seconds
        self._stop_requested = False
        self.items: list[NsuDocumentItem] = []

    def stop(self) -> None:
        """Solicita a interrupção da sincronização de NSU."""
        self._stop_requested = True

    def sync(
        self,
        start_nsu: str | int | None = None,
        max_batches: int | None = None,
        on_batch_start: Callable[[str, int], None] | None = None,
        on_doc_received: Callable[[NsuDocumentItem], None] | None = None,
        on_progress: Callable[[str, str, int], None] | None = None,
    ) -> dict[str, Any]:
        """
        Executa a esteira de sincronização por NSU.
        """
        self._stop_requested = False
        self.items = []

        if start_nsu is not None:
            current_nsu = str(start_nsu).zfill(15)
        else:
            state = self.registry.get_nsu_state(self.cnpj)
            current_nsu = state.get("ult_nsu", "000000000000000")

        max_nsu = "000000000000000"
        batches_processed = 0
        total_docs = 0
        full_xmls_saved = 0
        resumos_count = 0
        eventos_count = 0
        last_c_stat = 0
        last_x_motivo = ""

        while not self._stop_requested:
            batches_processed += 1
            if on_batch_start:
                on_batch_start(current_nsu, batches_processed)

            try:
                resp = execute_sefaz_nsu_query(
                    cnpj=self.cnpj,
                    cert_path=self.cert_path,
                    cert_password=self.cert_password,
                    ult_nsu=current_nsu,
                    c_uf_autor=self.c_uf_autor,
                    is_homologation=self.is_homologation,
                )
            except Exception as e:
                last_x_motivo = f"Falha de conexão: {e}"
                break

            last_c_stat = resp.c_stat
            last_x_motivo = resp.x_motivo

            if resp.ult_nsu:
                current_nsu = resp.ult_nsu.zfill(15)
            if resp.max_nsu:
                max_nsu = resp.max_nsu.zfill(15)

            # Salva o cursor no registro
            self.registry.update_nsu_state(self.cnpj, current_nsu, max_nsu)

            # 1. Documentos localizados (cStat 138)
            if resp.c_stat == 138 and resp.documents:
                for doc in resp.documents:
                    item = parse_nsu_doc_xml(doc.get("schema", ""), doc.get("nsu", ""), doc.get("xml", ""))

                    # Se for documento completo e tiver chave válida, salva o XML em disco
                    if item.doc_type in ("NF-e (Completa)", "CT-e (Completo)") and len(item.access_key) == 44:
                        fp = self.registry.store_xml(item.access_key, item.xml_content, c_stat=138)
                        item.file_path = str(fp.resolve())
                        full_xmls_saved += 1
                    elif "Resumo" in item.doc_type:
                        resumos_count += 1
                    elif "Evento" in item.doc_type:
                        eventos_count += 1

                    self.items.append(item)
                    total_docs += 1
                    if on_doc_received:
                        on_doc_received(item)

                if on_progress:
                    on_progress(current_nsu, max_nsu, total_docs)

                # Verifica se atingiu o fim da esteira
                try:
                    if int(current_nsu) >= int(max_nsu) and int(max_nsu) > 0:
                        break
                except ValueError:
                    pass

                if max_batches and batches_processed >= max_batches:
                    break

                # Pausa preventiva entre requisições
                if self.delay_seconds > 0 and not self._stop_requested:
                    time.sleep(self.delay_seconds)

            elif resp.c_stat == 137:
                # 137 = Nenhum documento localizado (fim da esteira de NSU)
                if on_progress:
                    on_progress(current_nsu, max_nsu, total_docs)
                break
            else:
                # Diretiva / Rejeição (cStat 656, etc.)
                self.registry.register_directive(resp.directive)
                break

        return {
            "c_stat": last_c_stat,
            "x_motivo": last_x_motivo,
            "last_c_stat": last_c_stat,
            "last_x_motivo": last_x_motivo,
            "ult_nsu": current_nsu,
            "max_nsu": max_nsu,
            "batches_processed": batches_processed,
            "total_docs": total_docs,
            "total_docs_received": total_docs,
            "full_xmls_saved": full_xmls_saved,
            "resumos_count": resumos_count,
            "eventos_count": eventos_count,
            "interrupted": self._stop_requested,
            "items": self.items,
        }



