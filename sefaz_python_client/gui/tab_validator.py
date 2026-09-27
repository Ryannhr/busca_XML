"""
Aba e Janela de Validação, Inspeção e Diagnóstico de XML de NF-e e DF-e (Individual e em Lote).
"""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from core.batch_processor import BatchFolderValidator, BatchXmlAuditRow
from core.xml_validator import XmlValidationReport, format_xml_string, inspect_and_validate_xml


class ValidatorTab(ttk.Frame):
    def __init__(self, parent: ttk.Notebook):
        super().__init__(parent, padding=12)
        self.current_report: XmlValidationReport | None = None
        self.batch_rows: list[BatchXmlAuditRow] = []
        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # 1. Barra de Ações Superior
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        btn_open = ttk.Button(toolbar, text="📂 Abrir Arquivo .XML", command=self._open_xml_file)
        btn_open.pack(side="left", padx=(0, 6))

        btn_batch_folder = ttk.Button(toolbar, text="📁 Validar Pasta Inteira (Lote)", command=self._open_batch_folder)
        btn_batch_folder.pack(side="left", padx=(0, 6))

        btn_validate = ttk.Button(toolbar, text="✓ Validar Conteúdo", command=self.run_validation)
        btn_validate.pack(side="left", padx=(0, 6))

        btn_clear = ttk.Button(toolbar, text="🗑️ Limpar", command=self._clear_all)
        btn_clear.pack(side="left", padx=(0, 6))

        btn_save = ttk.Button(toolbar, text="💾 Salvar XML", command=self._save_xml)
        btn_save.pack(side="right", padx=(6, 0))

        btn_danfe = ttk.Button(toolbar, text="📄 Gerar DANFE / DACTE (PDF)", command=self._generate_danfe)
        btn_danfe.pack(side="right", padx=(6, 0))

        btn_copy = ttk.Button(toolbar, text="📋 Copiar XML", command=self._copy_xml)
        btn_copy.pack(side="right", padx=(6, 0))

        # 2. Banner Visual de Status da Validação
        self.banner_frame = tk.Frame(self, bg="#e8f0fe", height=45, bd=1, relief="ridge")
        self.banner_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.banner_frame.pack_propagate(False)

        self.banner_label = tk.Label(
            self.banner_frame,
            text="Carregue um arquivo .xml ou selecione uma pasta inteira para validação em lote.",
            bg="#e8f0fe",
            fg="#1a73e8",
            font=("Segoe UI", 10, "bold"),
        )
        self.banner_label.pack(side="left", padx=12, expand=True)

        # 3. Sub-Notebook Principal do Validador
        self.sub_notebook = ttk.Notebook(self)
        self.sub_notebook.grid(row=2, column=0, sticky="nsew")

        # --- SUB-ABA 1: DIAGNÓSTICO E DADOS FISCAIS ---
        diag_tab = ttk.Frame(self.sub_notebook, padding=8)
        self.sub_notebook.add(diag_tab, text="  Diagnóstico e Campos Fiscais  ")
        diag_tab.columnconfigure(0, weight=1)
        diag_tab.columnconfigure(1, weight=1)
        diag_tab.rowconfigure(1, weight=1)

        # Seção Superior: Lista de Verificações de Validação
        chk_frame = ttk.LabelFrame(diag_tab, text=" Verificações de Validação Fiscal e Estrutural ", padding=8)
        chk_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        chk_frame.columnconfigure(0, weight=1)

        self.tree_checks = ttk.Treeview(chk_frame, columns=("status", "mensagem"), show="headings", height=4)
        self.tree_checks.heading("status", text="Nível")
        self.tree_checks.heading("mensagem", text="Diagnóstico")
        self.tree_checks.column("status", width=80, anchor="center", stretch=False)
        self.tree_checks.column("mensagem", width=600, anchor="w")
        self.tree_checks.pack(fill="x", expand=True)

        # Seção Inferior Esquerda: Decomposição da Chave
        key_frame = ttk.LabelFrame(diag_tab, text=" Decomposição da Chave de Acesso ", padding=8)
        key_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        key_frame.columnconfigure(1, weight=1)

        self.lbl_key_decomp = {}
        fields = [
            ("Chave de Acesso:", "full_key"),
            ("UF Autorizadora:", "uf"),
            ("Ano/Mês Emissão:", "aamm"),
            ("CNPJ Emitente:", "cnpj"),
            ("Modelo:", "modelo"),
            ("Série / Número:", "serie_num"),
            ("Tipo Emissão:", "tp_emis"),
            ("Dígito Verificador:", "dv"),
        ]
        for i, (label_txt, fkey) in enumerate(fields):
            ttk.Label(key_frame, text=label_txt, font=("Segoe UI", 9, "bold")).grid(row=i, column=0, sticky="w", pady=2)
            lbl = ttk.Label(key_frame, text="-", font=("Segoe UI", 9))
            lbl.grid(row=i, column=1, sticky="w", pady=2)
            self.lbl_key_decomp[fkey] = lbl

        # Seção Inferior Direita: Dados Comerciais e Autorização
        nfe_frame = ttk.LabelFrame(diag_tab, text=" Dados da NF-e e Autorização SEFAZ ", padding=8)
        nfe_frame.grid(row=1, column=1, sticky="nsew", padx=(4, 0))
        nfe_frame.columnconfigure(1, weight=1)

        self.lbl_nfe_data = {}
        nfe_fields = [
            ("Tipo de Documento:", "doc_type"),
            ("Número NF-e:", "nfe_num"),
            ("Data / Hora Emissão:", "dh_emi"),
            ("Emitente (Razão Social):", "emit_nome"),
            ("Destinatário (Razão):", "dest_nome"),
            ("Valor Total (R$):", "v_nf"),
            ("Protocolo SEFAZ:", "protocolo"),
            ("Status Autorização:", "cstat_auth"),
            ("Assinatura X.509:", "signature"),
        ]
        for i, (label_txt, fkey) in enumerate(nfe_fields):
            ttk.Label(nfe_frame, text=label_txt, font=("Segoe UI", 9, "bold")).grid(row=i, column=0, sticky="w", pady=2)
            lbl = ttk.Label(nfe_frame, text="-", font=("Segoe UI", 9))
            lbl.grid(row=i, column=1, sticky="w", pady=2)
            self.lbl_nfe_data[fkey] = lbl

        # --- SUB-ABA 2: VISUALIZADOR XML FORMATADO ---
        xml_tab = ttk.Frame(self.sub_notebook, padding=8)
        self.sub_notebook.add(xml_tab, text="  Visualizador do Código XML  ")
        xml_tab.columnconfigure(0, weight=1)
        xml_tab.rowconfigure(0, weight=1)

        self.xml_text_area = ScrolledText(xml_tab, wrap="none", font=("Consolas", 9))
        self.xml_text_area.grid(row=0, column=0, sticky="nsew")

        # --- SUB-ABA 3: AUDITORIA EM LOTE DE DIRETÓRIO ---
        batch_folder_tab = ttk.Frame(self.sub_notebook, padding=8)
        self.sub_notebook.add(batch_folder_tab, text="  📁 Auditoria em Lote de Pasta  ")
        batch_folder_tab.columnconfigure(0, weight=1)
        batch_folder_tab.rowconfigure(1, weight=1)

        # Barra de status do lote da pasta
        b_head = ttk.Frame(batch_folder_tab)
        b_head.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.lbl_batch_folder_info = ttk.Label(
            b_head,
            text="Nenhuma pasta auditada ainda. Clique em 'Validar Pasta Inteira (Lote)' para começar.",
            font=("Segoe UI", 9, "bold"),
        )
        self.lbl_batch_folder_info.pack(side="left")

        self.btn_batch_danfe = ttk.Button(
            b_head,
            text="📄 Gerar DANFEs da Pasta Inteira",
            state="disabled",
            command=self._generate_batch_danfes,
        )
        self.btn_batch_danfe.pack(side="right", padx=(6, 0))

        self.btn_export_csv = ttk.Button(
            b_head,
            text="📊 Exportar Relatório CSV",
            state="disabled",
            command=self._export_batch_csv,
        )
        self.btn_export_csv.pack(side="right")

        # Tabela com todos os XMLs da pasta
        batch_tree_container = ttk.Frame(batch_folder_tab)
        batch_tree_container.grid(row=1, column=0, sticky="nsew")
        batch_tree_container.columnconfigure(0, weight=1)
        batch_tree_container.rowconfigure(0, weight=1)

        b_cols = ("file", "status", "nfe", "serie", "val", "emit", "dest", "auth", "key")
        self.tree_folder = ttk.Treeview(batch_tree_container, columns=b_cols, show="headings", selectmode="browse")
        self.tree_folder.heading("file", text="Arquivo")
        self.tree_folder.heading("status", text="Status")
        self.tree_folder.heading("nfe", text="Nº NF-e")
        self.tree_folder.heading("serie", text="Série")
        self.tree_folder.heading("val", text="Valor Total (R$)")
        self.tree_folder.heading("emit", text="Emitente")
        self.tree_folder.heading("dest", text="Destinatário")
        self.tree_folder.heading("auth", text="Protocolo")
        self.tree_folder.heading("key", text="Chave de Acesso")

        self.tree_folder.column("file", width=140, anchor="w")
        self.tree_folder.column("status", width=75, anchor="center")
        self.tree_folder.column("nfe", width=70, anchor="center")
        self.tree_folder.column("serie", width=50, anchor="center")
        self.tree_folder.column("val", width=95, anchor="e")
        self.tree_folder.column("emit", width=160, anchor="w")
        self.tree_folder.column("dest", width=160, anchor="w")
        self.tree_folder.column("auth", width=100, anchor="center")
        self.tree_folder.column("key", width=240, anchor="w")

        b_scroll_y = ttk.Scrollbar(batch_tree_container, orient="vertical", command=self.tree_folder.yview)
        b_scroll_x = ttk.Scrollbar(batch_tree_container, orient="horizontal", command=self.tree_folder.xview)
        self.tree_folder.configure(yscrollcommand=b_scroll_y.set, xscrollcommand=b_scroll_x.set)

        self.tree_folder.grid(row=0, column=0, sticky="nsew")
        b_scroll_y.grid(row=0, column=1, sticky="ns")
        b_scroll_x.grid(row=1, column=0, sticky="ew")

        self.tree_folder.bind("<Double-1>", self._on_folder_row_double_click)

    def load_xml_content(self, xml_text: str, key_hint: str = "") -> None:
        """Carrega conteúdo XML externamente."""
        self.xml_text_area.delete("1.0", "end")
        self.xml_text_area.insert("1.0", format_xml_string(xml_text))
        self.run_validation()
        self.sub_notebook.select(0)

    def _open_xml_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Selecione o arquivo XML de NF-e",
            filetypes=[("Arquivos XML", "*.xml"), ("Todos os arquivos", "*.*")],
        )
        if filename:
            try:
                p = Path(filename)
                try:
                    content = p.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    content = p.read_text(encoding="latin-1")
                self.load_xml_content(content)
            except Exception as e:
                messagebox.showerror("Erro de Leitura", f"Não foi possível abrir o arquivo XML:\n{e}")

    def run_validation(self) -> None:
        content = self.xml_text_area.get("1.0", "end").strip()
        if not content:
            messagebox.showwarning("Aviso", "A área de XML está vazia. Abra um arquivo ou cole o conteúdo XML primeiro.")
            return

        report = inspect_and_validate_xml(content)
        self.current_report = report

        # 1. Atualiza Banner de Status
        if not report.is_valid_syntax:
            self.banner_frame.config(bg="#fce8e6")
            self.banner_label.config(
                text="❌ ERRO DE SINTAXE: O arquivo não é um XML válido.",
                bg="#fce8e6",
                fg="#d93025",
            )
        elif not report.is_valid_key:
            self.banner_frame.config(bg="#fef7e0")
            self.banner_label.config(
                text="⚠️ ALERTA: XML bem-formado, mas a Chave de Acesso possui divergências fiscais.",
                bg="#fef7e0",
                fg="#b06000",
            )
        elif report.authorization_data.get("cStat") == "100":
            self.banner_frame.config(bg="#e6f4ea")
            self.banner_label.config(
                text="✅ NF-e VÁLIDA E AUTORIZADA: Chave verificada e protocolo de autorização 100 presente!",
                bg="#e6f4ea",
                fg="#188038",
            )
        else:
            self.banner_frame.config(bg="#e8f0fe")
            self.banner_label.config(
                text=f"ℹ️ DOCUMENTO IDENTIFICADO: <{report.doc_type}> - Chave íntegra e sintaxe válida.",
                bg="#e8f0fe",
                fg="#1a73e8",
            )

        # 2. Atualiza Tabela de Diagnósticos
        for row_id in self.tree_checks.get_children():
            self.tree_checks.delete(row_id)

        for item in report.messages:
            self.tree_checks.insert("", "end", values=(item["level"], item["text"]))

        # 3. Atualiza Decomposição da Chave
        kd = report.key_details
        if kd:
            self.lbl_key_decomp["full_key"].config(text=report.access_key or "-")
            self.lbl_key_decomp["uf"].config(text=kd.get("uf_name", "-"))
            self.lbl_key_decomp["aamm"].config(text=kd.get("ano_mes", "-"))
            self.lbl_key_decomp["cnpj"].config(text=kd.get("emit_cnpj", "-"))
            self.lbl_key_decomp["modelo"].config(text=kd.get("modelo", "-"))
            self.lbl_key_decomp["serie_num"].config(text=f"Série {kd.get('serie')} / Nº {kd.get('numero')}")
            self.lbl_key_decomp["tp_emis"].config(text=kd.get("tp_emis", "-"))

            dv_text = f"XML: {kd.get('c_dv')} | Recalculado: {kd.get('expected_dv')}"
            if kd.get("dv_match"):
                dv_text += " (CONFERE ✓)"
                self.lbl_key_decomp["dv"].config(text=dv_text, foreground="green")
            else:
                dv_text += " (DIVERGENTE ✗)"
                self.lbl_key_decomp["dv"].config(text=dv_text, foreground="red")
        else:
            for lbl in self.lbl_key_decomp.values():
                lbl.config(text="-", foreground="black")

        # 4. Atualiza Dados da NF-e e Autorização
        nd = report.nfe_data
        self.lbl_nfe_data["doc_type"].config(text=f"<{report.doc_type}>")
        self.lbl_nfe_data["nfe_num"].config(text=nd.get("nNF", "-"))
        self.lbl_nfe_data["dh_emi"].config(text=nd.get("dhEmi", "-"))
        self.lbl_nfe_data["emit_nome"].config(text=f"{nd.get('emit_nome', '-')} ({nd.get('emit_doc', '')})")
        self.lbl_nfe_data["dest_nome"].config(text=f"{nd.get('dest_nome', '-')} ({nd.get('dest_doc', '')})")

        val_total = nd.get("vNF")
        if val_total:
            try:
                formatted_val = f"R$ {float(val_total):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                self.lbl_nfe_data["v_nf"].config(text=formatted_val)
            except ValueError:
                self.lbl_nfe_data["v_nf"].config(text=f"R$ {val_total}")
        else:
            self.lbl_nfe_data["v_nf"].config(text="-")

        auth = report.authorization_data
        if auth:
            self.lbl_nfe_data["protocolo"].config(text=auth.get("nProt", "-"))
            c_stat = auth.get("cStat", "")
            motivo = auth.get("xMotivo", "")
            self.lbl_nfe_data["cstat_auth"].config(
                text=f"{c_stat} - {motivo}",
                foreground="green" if c_stat == "100" else "orange",
            )
        else:
            self.lbl_nfe_data["protocolo"].config(text="Não encontrado")
            self.lbl_nfe_data["cstat_auth"].config(text="Sem protocolo", foreground="gray")

        if report.signature_found:
            self.lbl_nfe_data["signature"].config(text="Presente e íntegra ✓", foreground="green")
        else:
            self.lbl_nfe_data["signature"].config(text="Não localizada ✗", foreground="orange")

    # --- AUDITORIA EM LOTE DE PASTA ---
    def _open_batch_folder(self) -> None:
        folder = filedialog.askdirectory(title="Selecione a Pasta contendo os arquivos XML")
        if not folder:
            return

        self.banner_frame.config(bg="#e8f0fe")
        self.banner_label.config(text=f"Auditando pasta: {folder}...", bg="#e8f0fe", fg="#1a73e8")

        def task():
            try:
                rows = BatchFolderValidator.scan_and_validate_directory(folder)
                self.after(0, lambda: self._on_batch_folder_completed(folder, rows))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Erro ao Validar Pasta", str(e)))

        threading.Thread(target=task, daemon=True).start()

    def _on_batch_folder_completed(self, folder_path: str, rows: list[BatchXmlAuditRow]) -> None:
        self.batch_rows = rows
        for r_id in self.tree_folder.get_children():
            self.tree_folder.delete(r_id)

        valid_count = sum(1 for r in rows if r.status == "VÁLIDO")
        warn_count = sum(1 for r in rows if r.status == "ALERTA")
        err_count = sum(1 for r in rows if r.status == "ERRO")

        for i, r in enumerate(rows):
            try:
                val_num = float(r.total_value)
                val_str = f"R$ {val_num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            except ValueError:
                val_str = r.total_value

            self.tree_folder.insert("", "end", iid=str(i), values=(
                r.file_name,
                r.status,
                r.nfe_number,
                r.series,
                val_str,
                r.emit_name,
                r.dest_name,
                f"{r.cstat_auth} ({r.protocol_num[:8]}...)" if r.protocol_num != "-" else "-",
                r.access_key,
            ))

        info_msg = f"Auditoria Concluída: {len(rows)} arquivos XML analisados | {valid_count} Válidos | {warn_count} Alertas | {err_count} Erros"
        self.lbl_batch_folder_info.config(text=info_msg)

        if err_count > 0:
            self.banner_frame.config(bg="#fce8e6")
            self.banner_label.config(text=f"⚠️ {info_msg}", bg="#fce8e6", fg="#d93025")
        else:
            self.banner_frame.config(bg="#e6f4ea")
            self.banner_label.config(text=f"✅ {info_msg}", bg="#e6f4ea", fg="#188038")

        self.last_audited_folder = folder_path
        valid_candidates = [r for r in rows if r.status in ("VÁLIDO", "ALERTA")]
        self.btn_export_csv.config(state="normal" if rows else "disabled")
        self.btn_batch_danfe.config(state="normal" if valid_candidates else "disabled")
        self.sub_notebook.select(2)  # Muda para a aba da tabela em lote

    def _on_folder_row_double_click(self, event) -> None:
        selected = self.tree_folder.selection()
        if not selected:
            return
        idx = int(selected[0])
        row = self.batch_rows[idx]
        fp = Path(row.file_path)
        if fp.exists():
            try:
                content = fp.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = fp.read_text(encoding="latin-1")
            self.load_xml_content(content, row.access_key)
            self.sub_notebook.select(0)  # Volta para a aba de diagnóstico individual

    def _export_batch_csv(self) -> None:
        if not self.batch_rows:
            messagebox.showwarning("Aviso", "Nenhum dado auditado para exportar.")
            return

        filepath = filedialog.asksaveasfilename(
            title="Salvar Relatório Consolidado em CSV",
            initialfile="relatorio_auditoria_xmls.csv",
            defaultextension=".csv",
            filetypes=[("Arquivos CSV (Excel)", "*.csv"), ("Todos os arquivos", "*.*")],
        )
        if filepath:
            try:
                BatchFolderValidator.export_to_csv(self.batch_rows, filepath)
                messagebox.showinfo("Exportado com Sucesso", f"Relatório de {len(self.batch_rows)} notas fiscais exportado para:\n{filepath}")
            except Exception as e:
                messagebox.showerror("Erro na Exportação", f"Não foi possível salvar o CSV:\n{e}")

    def _clear_all(self) -> None:
        self.xml_text_area.delete("1.0", "end")
        self.current_report = None
        self.banner_frame.config(bg="#e8f0fe")
        self.banner_label.config(
            text="Carregue um arquivo .xml ou selecione uma pasta inteira para validação em lote.",
            bg="#e8f0fe",
            fg="#1a73e8",
        )
        for row_id in self.tree_checks.get_children():
            self.tree_checks.delete(row_id)
        for lbl in self.lbl_key_decomp.values():
            lbl.config(text="-", foreground="black")
        for lbl in self.lbl_nfe_data.values():
            lbl.config(text="-", foreground="black")
        self.btn_export_csv.config(state="disabled")
        self.btn_batch_danfe.config(state="disabled")

    def _copy_xml(self) -> None:
        content = self.xml_text_area.get("1.0", "end").strip()
        if not content:
            messagebox.showwarning("Aviso", "Não há conteúdo para copiar.")
            return
        self.clipboard_clear()
        self.clipboard_append(content)
        messagebox.showinfo("Copiado", "Conteúdo do XML copiado para a área de transferência!")

    def _save_xml(self) -> None:
        content = self.xml_text_area.get("1.0", "end").strip()
        if not content:
            messagebox.showwarning("Aviso", "Não há conteúdo para salvar.")
            return

        default_name = "nfe.xml"
        if self.current_report and self.current_report.access_key:
            default_name = f"{self.current_report.access_key}.xml"

        filepath = filedialog.asksaveasfilename(
            title="Salvar Arquivo XML",
            initialfile=default_name,
            defaultextension=".xml",
            filetypes=[("Arquivos XML", "*.xml"), ("Todos os arquivos", "*.*")],
        )
        if filepath:
            try:
                Path(filepath).write_text(content, encoding="utf-8")
                messagebox.showinfo("Salvo", f"Arquivo XML salvo com sucesso em:\n{filepath}")
            except Exception as e:
                messagebox.showerror("Erro ao Salvar", f"Não foi possível salvar o arquivo:\n{e}")

    def _generate_danfe(self) -> None:
        content = self.xml_text_area.get("1.0", "end").strip()
        if not content:
            messagebox.showwarning("Aviso", "A área de XML está vazia. Abra um arquivo ou valide um XML primeiro.")
            return

        from core.danfe_generator import detect_document_type, generate_fiscal_document_pdf, open_pdf_file
        key_hint = self.current_report.access_key if (self.current_report and self.current_report.access_key) else ""
        doc_type = detect_document_type(key_hint or content)
        doc_name = "DACTE" if doc_type == "CTE" else "DANFE"
        default_name = f"{doc_name}_{key_hint or 'doc'}.pdf"

        filepath = filedialog.asksaveasfilename(
            title=f"Salvar {doc_name} em PDF",
            initialfile=default_name,
            defaultextension=".pdf",
            filetypes=[("Documentos PDF (*.pdf)", "*.pdf"), ("Todos os arquivos", "*.*")],
        )
        if filepath:
            try:
                _, out_path = generate_fiscal_document_pdf(content, output_pdf_path=filepath)
                open_now = messagebox.askyesno(
                    f"{doc_name} Gerado com Sucesso",
                    f"{doc_name} em PDF gerado com sucesso!\nSalvo em:\n{out_path}\n\nDeseja abrir o arquivo PDF agora?",
                )
                if open_now:
                    open_pdf_file(out_path)
            except Exception as e:
                messagebox.showerror(f"Erro ao Gerar {doc_name}", f"Não foi possível gerar o {doc_name} em PDF:\n{e}")

    def _generate_batch_danfes(self) -> None:
        if not self.batch_rows:
            messagebox.showwarning("Aviso", "Nenhuma pasta foi auditada ainda.")
            return

        valid_rows = [r for r in self.batch_rows if r.status in ("VÁLIDO", "ALERTA") and Path(r.file_path).exists()]
        if not valid_rows:
            messagebox.showwarning("Aviso", "Nenhum arquivo XML válido ou com alerta encontrado para gerar DANFE.")
            return

        initial_dir = getattr(self, "last_audited_folder", "")
        out_folder = filedialog.askdirectory(
            title=f"Selecione a pasta para salvar os {len(valid_rows)} DANFEs em PDF",
            initialdir=initial_dir or None,
        )
        if not out_folder:
            return

        progress_win = tk.Toplevel(self)
        progress_win.title("Gerando DANFEs em Lote")
        progress_win.geometry("460x160")
        progress_win.transient(self)
        progress_win.grab_set()

        lbl_status = ttk.Label(progress_win, text=f"Iniciando conversão de {len(valid_rows)} notas fiscais...", font=("Segoe UI", 9, "bold"))
        lbl_status.pack(pady=(15, 6), padx=15, anchor="w")

        pbar = ttk.Progressbar(progress_win, mode="determinate", maximum=len(valid_rows))
        pbar.pack(fill="x", padx=15, pady=6)

        lbl_detail = ttk.Label(progress_win, text="Preparando...", font=("Segoe UI", 8), foreground="gray")
        lbl_detail.pack(pady=(2, 15), padx=15, anchor="w")

        def update_prog(cur: int, tot: int, name: str):
            def _ui():
                pbar["value"] = cur
                lbl_status.config(text=f"Convertendo {cur} de {tot} notas...")
                lbl_detail.config(text=f"Gerado: {name}")
            progress_win.after(0, _ui)

        def run_task():
            try:
                res = BatchFolderValidator.generate_danfes_for_rows(
                    rows=self.batch_rows,
                    output_directory=out_folder,
                    on_progress=update_prog,
                )
                def _done():
                    progress_win.destroy()
                    msg = (
                        f"Conversão em Lote Concluída com Sucesso!\n\n"
                        f"• Total de DANFEs gerados: {res['generated_count']}\n"
                        f"• Falhas / Erros: {res['error_count']}\n"
                        f"• Pasta de Destino:\n{res['output_directory']}\n\n"
                        f"Deseja abrir a pasta dos PDFs agora?"
                    )
                    open_dir = messagebox.askyesno("DANFEs Gerados", msg, icon="info")
                    if open_dir:
                        from core.danfe_generator import open_pdf_file
                        open_pdf_file(res["output_directory"])
                self.after(0, _done)
            except Exception as e:
                def _err():
                    progress_win.destroy()
                    messagebox.showerror("Erro ao Gerar DANFEs", f"Falha na geração em lote:\n{e}")
                self.after(0, _err)

        threading.Thread(target=run_task, daemon=True).start()

