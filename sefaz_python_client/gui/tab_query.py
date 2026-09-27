"""
Aba de Consulta e Download de NF-e na SEFAZ DF-e (Individual e em Lote).
"""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from core.batch_processor import (
    BatchQueryItem,
    BatchQueryManager,
    NsuDocumentItem,
    NsuSyncManager,
    extract_keys_from_file,
    extract_keys_from_text,
)
from core.constants import UF_IBGE_MAP
from core.registry import SefazLocalRegistry
from core.rules import validate_nfe_access_key
from core.service import search_nfe_xml


class QueryTab(ttk.Frame):
    def __init__(
        self,
        parent: ttk.Notebook,
        registry: SefazLocalRegistry,
        on_xml_ready_for_validation: Callable[[str, str], None],
    ):
        super().__init__(parent, padding=12)
        self.registry = registry
        self.on_xml_ready_for_validation = on_xml_ready_for_validation
        self.last_downloaded_xml: str | None = None
        self.last_downloaded_key: str | None = None
        self.batch_manager: BatchQueryManager | None = None
        self.batch_items: list[BatchQueryItem] = []
        self.nsu_manager: NsuSyncManager | None = None
        self.nsu_items: list[NsuDocumentItem] = []

        self._build_ui()
        self.refresh_status()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)

        # Painel Esquerdo: Parâmetros e Modo de Consulta
        left_container = ttk.Frame(self)
        left_container.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left_container.columnconfigure(0, weight=1)
        left_container.rowconfigure(1, weight=1)

        # Configurações Comuns (Certificado, CNPJ, Ambiente)
        common_frame = ttk.LabelFrame(left_container, text=" Credenciais e Ambiente SEFAZ ", padding=10)
        common_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        common_frame.columnconfigure(1, weight=1)

        # CNPJ Consulente
        ttk.Label(common_frame, text="CNPJ Consulente:").grid(row=0, column=0, sticky="w", pady=3)
        self.cnpj_var = tk.StringVar()
        self.cnpj_var.trace_add("write", lambda *_: self._update_nsu_cursor_display())
        self.cnpj_entry = ttk.Entry(common_frame, textvariable=self.cnpj_var, font=("Consolas", 10))
        self.cnpj_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=3)

        # Certificado A1
        ttk.Label(common_frame, text="Certificado A1:").grid(row=1, column=0, sticky="w", pady=3)
        self.cert_var = tk.StringVar()
        self.cert_entry = ttk.Entry(common_frame, textvariable=self.cert_var, font=("Segoe UI", 9))
        self.cert_entry.grid(row=1, column=1, sticky="ew", pady=3, padx=(0, 4))
        self.btn_browse = ttk.Button(common_frame, text="Procurar...", command=self._browse_cert)
        self.btn_browse.grid(row=1, column=2, sticky="e", pady=3)

        # Senha
        ttk.Label(common_frame, text="Senha Certificado:").grid(row=2, column=0, sticky="w", pady=3)
        self.pass_var = tk.StringVar()
        self.pass_entry = ttk.Entry(common_frame, textvariable=self.pass_var, show="*", font=("Consolas", 10))
        self.pass_entry.grid(row=2, column=1, sticky="ew", pady=3, padx=(0, 4))
        self.show_pass_var = tk.BooleanVar(value=False)
        self.chk_pass = ttk.Checkbutton(common_frame, text="Exibir", variable=self.show_pass_var, command=self._toggle_pass)
        self.chk_pass.grid(row=2, column=2, sticky="w", pady=3)

        # Status / Verificação do Certificado
        cert_test_frame = ttk.Frame(common_frame)
        cert_test_frame.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(1, 3))
        btn_test_cert = ttk.Button(cert_test_frame, text="🔐 Testar Validade do Certificado", command=self._test_certificate)
        btn_test_cert.pack(side="left", padx=(0, 6))
        self.lbl_cert_info = ttk.Label(cert_test_frame, text="", font=("Segoe UI", 8, "italic"))
        self.lbl_cert_info.pack(side="left")

        # Ambiente
        ttk.Label(common_frame, text="Ambiente:").grid(row=4, column=0, sticky="w", pady=3)
        self.env_var = tk.StringVar(value="1")
        env_frame = ttk.Frame(common_frame)
        env_frame.grid(row=4, column=1, columnspan=2, sticky="w", pady=3)
        ttk.Radiobutton(env_frame, text="Produção", variable=self.env_var, value="1").pack(side="left", padx=(0, 15))
        ttk.Radiobutton(env_frame, text="Homologação (Testes)", variable=self.env_var, value="2").pack(side="left")

        # Sub-Notebook para alternar entre "Consulta Individual" e "Consulta em Lote"
        self.query_mode_notebook = ttk.Notebook(left_container)
        self.query_mode_notebook.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

        # --- SUB-ABA A: CONSULTA INDIVIDUAL ---
        indiv_tab = ttk.Frame(self.query_mode_notebook, padding=10)
        self.query_mode_notebook.add(indiv_tab, text="  Chave Individual  ")
        indiv_tab.columnconfigure(1, weight=1)

        ttk.Label(indiv_tab, text="Chave de Acesso (44 dígitos):").grid(row=0, column=0, sticky="w", pady=4)
        self.key_var = tk.StringVar()
        self.key_var.trace_add("write", self._on_key_changed)
        self.key_entry = ttk.Entry(indiv_tab, textvariable=self.key_var, font=("Consolas", 10))
        self.key_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)

        self.key_info_label = ttk.Label(indiv_tab, text="Digite a chave da NF-e", font=("Segoe UI", 9, "italic"), foreground="gray")
        self.key_info_label.grid(row=1, column=1, columnspan=2, sticky="w", pady=(0, 10))

        btn_box = ttk.Frame(indiv_tab)
        btn_box.grid(row=2, column=0, columnspan=3, sticky="ew", pady=6)
        btn_box.columnconfigure(0, weight=1)
        btn_box.columnconfigure(1, weight=2)

        self.btn_dry_run = ttk.Button(btn_box, text=" Validar / Dry-Run", command=self._handle_dry_run)
        self.btn_dry_run.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.btn_search = ttk.Button(btn_box, text="⬇️ Consultar SEFAZ & Baixar XML", command=self._handle_search)
        self.btn_search.grid(row=0, column=1, sticky="ew")

        # Ações pós-download (Validador e DANFE)
        action_box = ttk.Frame(indiv_tab)
        action_box.grid(row=3, column=0, columnspan=3, sticky="ew", pady=10)
        action_box.columnconfigure(0, weight=1)
        action_box.columnconfigure(1, weight=1)

        self.btn_send_to_validator = ttk.Button(
            action_box,
            text="Inspecionar no Validador",
            state="disabled",
            command=self._send_to_validator,
        )
        self.btn_send_to_validator.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.btn_generate_danfe = ttk.Button(
            action_box,
            text="Gerar DANFE (PDF)",
            state="disabled",
            command=self._generate_danfe,
        )
        self.btn_generate_danfe.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # --- SUB-ABA B: CONSULTA EM LOTE ---
        batch_tab = ttk.Frame(self.query_mode_notebook, padding=10)
        self.query_mode_notebook.add(batch_tab, text=" Consulta em Lote (Múltiplas Chaves)  ")
        batch_tab.columnconfigure(0, weight=1)
        batch_tab.rowconfigure(3, weight=1)

        # Barra de ferramentas do lote
        batch_tools = ttk.Frame(batch_tab)
        batch_tools.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        btn_load_file = ttk.Button(batch_tools, text=" Importar TXT / CSV", command=self._import_batch_file)
        btn_load_file.pack(side="left", padx=(0, 6))

        btn_paste = ttk.Button(batch_tools, text=" Colar Lista de Chaves", command=self._open_paste_dialog)
        btn_paste.pack(side="left", padx=(0, 6))

        self.btn_start_batch = ttk.Button(batch_tools, text="▶ Iniciar / Continuar Lote", command=self._start_batch_processing)
        self.btn_start_batch.pack(side="left", padx=(0, 6))

        self.btn_stop_batch = ttk.Button(batch_tools, text="⏹ Interromper", state="disabled", command=self._stop_batch_processing)
        self.btn_stop_batch.pack(side="left", padx=(0, 6))

        btn_clear_batch = ttk.Button(batch_tools, text="🗑️ Limpar", command=self._clear_batch_list)
        btn_clear_batch.pack(side="right")

        # Opções de Automação e Continuidade (Piloto Automático)
        batch_options = ttk.Frame(batch_tab)
        batch_options.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        self.batch_auto_wait_var = tk.BooleanVar(value=True)
        self.chk_auto_wait = ttk.Checkbutton(
            batch_options,
            text="🤖 Piloto Automático: aguardar liberação de cota (15/h) e continuar sozinho sem parar",
            variable=self.batch_auto_wait_var,
        )
        self.chk_auto_wait.pack(side="left")

        self.lbl_batch_countdown = ttk.Label(batch_options, text="", font=("Segoe UI", 9, "bold"), foreground="#1a73e8")
        self.lbl_batch_countdown.pack(side="right")

        # Status do lote
        self.lbl_batch_summary = ttk.Label(batch_tab, text="Nenhuma lista de chaves carregada.", font=("Segoe UI", 9, "bold"))
        self.lbl_batch_summary.grid(row=2, column=0, sticky="w", pady=(0, 4))

        # Tabela da fila de lote
        tree_container = ttk.Frame(batch_tab)
        tree_container.grid(row=3, column=0, sticky="nsew")
        tree_container.columnconfigure(0, weight=1)
        tree_container.rowconfigure(0, weight=1)

        columns = ("key", "status", "source", "details")
        self.tree_batch = ttk.Treeview(tree_container, columns=columns, show="headings", selectmode="browse")
        self.tree_batch.heading("key", text="Chave de Acesso (44)")
        self.tree_batch.heading("status", text="Status")
        self.tree_batch.heading("source", text="Origem")
        self.tree_batch.heading("details", text="Mensagem / Diagnóstico")

        self.tree_batch.column("key", width=250, anchor="w")
        self.tree_batch.column("status", width=90, anchor="center")
        self.tree_batch.column("source", width=95, anchor="center")
        self.tree_batch.column("details", width=220, anchor="w")

        scroll_y = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree_batch.yview)
        self.tree_batch.configure(yscrollcommand=scroll_y.set)

        self.tree_batch.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")

        self.tree_batch.bind("<Double-1>", self._on_batch_row_double_click)

        # --- SUB-ABA C: SINCRONIZAÇÃO POR NSU (LOTE OFICIAL SEFAZ) ---
        nsu_tab = ttk.Frame(self.query_mode_notebook, padding=10)
        self.query_mode_notebook.add(nsu_tab, text=" Sincronização por NSU (Lote SEFAZ) ")
        nsu_tab.columnconfigure(0, weight=1)
        nsu_tab.rowconfigure(3, weight=1)

        # 1. Informações explicativas
        nsu_banner = ttk.Label(
            nsu_tab,
            text="💡 O método NSU busca em lote até 50 documentos por requisição contra o seu CNPJ na SEFAZ.\n"
                 "Ideal para sincronizar centenas ou milhares de notas emitidas contra a empresa sem estourar cotas.",
            font=("Segoe UI", 9, "italic"),
            foreground="#1a73e8",
            justify="left",
        )
        nsu_banner.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # 2. Parâmetros de sincronização
        nsu_params = ttk.Frame(nsu_tab)
        nsu_params.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        nsu_params.columnconfigure(1, weight=1)
        nsu_params.columnconfigure(3, weight=1)

        ttk.Label(nsu_params, text="UF Autorizadora:").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=2)
        self.nsu_uf_var = tk.StringVar(value="SP")
        uf_options = list(UF_IBGE_MAP.keys())
        self.nsu_uf_combo = ttk.Combobox(nsu_params, textvariable=self.nsu_uf_var, values=uf_options, width=8, state="readonly")
        self.nsu_uf_combo.grid(row=0, column=1, sticky="w", padx=(0, 15), pady=2)

        ttk.Label(nsu_params, text="Último NSU (Cursor):").grid(row=0, column=2, sticky="w", padx=(0, 4), pady=2)
        self.nsu_var = tk.StringVar(value="000000000000000")
        self.nsu_entry = ttk.Entry(nsu_params, textvariable=self.nsu_var, font=("Consolas", 10), width=18)
        self.nsu_entry.grid(row=0, column=3, sticky="w", pady=2)

        # 3. Barra de ferramentas e Ações do NSU
        nsu_tools = ttk.Frame(nsu_tab)
        nsu_tools.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        self.btn_start_nsu = ttk.Button(nsu_tools, text="▶ Iniciar Sincronização NSU", command=self._start_nsu_sync)
        self.btn_start_nsu.pack(side="left", padx=(0, 6))

        self.btn_stop_nsu = ttk.Button(nsu_tools, text="⏹ Interromper", state="disabled", command=self._stop_nsu_sync)
        self.btn_stop_nsu.pack(side="left", padx=(0, 6))

        self.btn_reset_nsu = ttk.Button(nsu_tools, text="🔄 Resetar para NSU 0", command=self._reset_nsu)
        self.btn_reset_nsu.pack(side="left", padx=(0, 6))

        btn_clear_nsu = ttk.Button(nsu_tools, text="🗑️ Limpar Tabela", command=self._clear_nsu_list)
        btn_clear_nsu.pack(side="right")

        # 4. Painel de Status e Tabela de Resultados
        nsu_table_container = ttk.Frame(nsu_tab)
        nsu_table_container.grid(row=3, column=0, sticky="nsew")
        nsu_table_container.columnconfigure(0, weight=1)
        nsu_table_container.rowconfigure(1, weight=1)

        self.lbl_nsu_summary = ttk.Label(
            nsu_table_container,
            text="Status: Pronto para iniciar | Último NSU: 000000000000000 | Maior NSU: 000000000000000 | Documentos: 0",
            font=("Segoe UI", 9, "bold"),
        )
        self.lbl_nsu_summary.grid(row=0, column=0, sticky="w", pady=(0, 4))

        nsu_cols = ("nsu", "tipo", "chave", "emitente", "valor", "data", "status")
        self.tree_nsu = ttk.Treeview(nsu_table_container, columns=nsu_cols, show="headings", selectmode="browse")
        self.tree_nsu.heading("nsu", text="NSU")
        self.tree_nsu.heading("tipo", text="Tipo")
        self.tree_nsu.heading("chave", text="Chave de Acesso (44)")
        self.tree_nsu.heading("emitente", text="Emitente")
        self.tree_nsu.heading("valor", text="Valor (R$)")
        self.tree_nsu.heading("data", text="Data Emissão")
        self.tree_nsu.heading("status", text="Arquivo / Status")

        self.tree_nsu.column("nsu", width=85, anchor="center")
        self.tree_nsu.column("tipo", width=110, anchor="center")
        self.tree_nsu.column("chave", width=250, anchor="w")
        self.tree_nsu.column("emitente", width=160, anchor="w")
        self.tree_nsu.column("valor", width=90, anchor="e")
        self.tree_nsu.column("data", width=110, anchor="center")
        self.tree_nsu.column("status", width=140, anchor="w")

        scroll_nsu_y = ttk.Scrollbar(nsu_table_container, orient="vertical", command=self.tree_nsu.yview)
        self.tree_nsu.configure(yscrollcommand=scroll_nsu_y.set)

        self.tree_nsu.grid(row=1, column=0, sticky="nsew")
        scroll_nsu_y.grid(row=1, column=1, sticky="ns")

        self.tree_nsu.bind("<Double-1>", self._on_nsu_row_double_click)

        # Barra de Progresso Geral
        self.progress = ttk.Progressbar(left_container, mode="determinate")
        self.progress.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        # --- PAINEL DIREITA: STATUS FISCAL & LOGS ---
        right_frame = ttk.LabelFrame(self, text=" Status e Monitoramento ", padding=10)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(2, weight=1)

        status_card = ttk.Frame(right_frame, relief="groove", padding=8)
        status_card.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        status_card.columnconfigure(1, weight=1)

        ttk.Label(status_card, text="Consultas na última hora:", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=2)
        self.lbl_rate = ttk.Label(status_card, text="0 / 15", font=("Segoe UI", 9))
        self.lbl_rate.grid(row=0, column=1, sticky="e", pady=2)

        ttk.Label(status_card, text="Liberação de Cota:", font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w", pady=2)
        self.lbl_next_slot = ttk.Label(status_card, text="Disponível agora", font=("Segoe UI", 8), foreground="#1a73e8")
        self.lbl_next_slot.grid(row=1, column=1, sticky="e", pady=2)

        ttk.Label(status_card, text="Status de Bloqueio SEFAZ:", font=("Segoe UI", 9, "bold")).grid(row=2, column=0, sticky="w", pady=2)
        self.lbl_block = ttk.Label(status_card, text="Livre (Sem travas)", foreground="green", font=("Segoe UI", 9, "bold"))
        self.lbl_block.grid(row=2, column=1, sticky="e", pady=2)

        ttk.Label(status_card, text="XMLs em Cache Local:", font=("Segoe UI", 9, "bold")).grid(row=3, column=0, sticky="w", pady=2)
        self.lbl_cache = ttk.Label(status_card, text="0 notas", font=("Segoe UI", 9))
        self.lbl_cache.grid(row=3, column=1, sticky="e", pady=2)

        btn_refresh = ttk.Button(status_card, text="Atualizar Status e Histórico", command=self.refresh_status)
        btn_refresh.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 2))

        ttk.Label(right_frame, text="Log de Atividades:", font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w", pady=(4, 2))

        self.log_text = ScrolledText(right_frame, wrap="word", height=15, font=("Consolas", 9))
        self.log_text.grid(row=2, column=0, sticky="nsew")
        self.log_text.tag_config("INFO", foreground="#1a73e8")
        self.log_text.tag_config("SUCCESS", foreground="#188038")
        self.log_text.tag_config("WARN", foreground="#b06000")
        self.log_text.tag_config("ERROR", foreground="#d93025")

        self.log("INFO", "Cliente SEFAZ DF-e pronto (Modos Individual e Lote ativados).")

    def log(self, level: str, message: str) -> None:
        self.log_text.insert("end", f"[{level}] {message}\n", level)
        self.log_text.see("end")

    def _toggle_pass(self) -> None:
        self.pass_entry.config(show="" if self.show_pass_var.get() else "*")

    def _browse_cert(self) -> None:
        filename = filedialog.askopenfilename(
            title="Selecione o Certificado Digital A1",
            filetypes=[("Certificado Digital A1", "*.pfx *.p12"), ("Todos os arquivos", "*.*")],
        )
        if filename:
            self.cert_var.set(filename)

    def _test_certificate(self) -> None:
        cert = self.cert_var.get().strip()
        pwd = self.pass_var.get()
        if not cert:
            messagebox.showwarning("Aviso", "Selecione o arquivo do certificado A1 (.pfx/.p12).")
            return
        from core.certificate import inspect_certificate
        try:
            info = inspect_certificate(cert, pwd)
            if info["is_expired"]:
                self.lbl_cert_info.config(text=f"✗ EXPIRADO em {info['valid_until']}", foreground="red")
                self.log("ERROR", f"Certificado de {info['subject_cn']} expirou em {info['valid_until']}.")
                messagebox.showerror(
                    "Certificado Expirado",
                    f"O certificado de:\n{info['subject_cn']}\n\nEXPIROU em: {info['valid_until']}.\n"
                    "A SEFAZ não aceita certificados digitais vencidos.",
                )
            elif info["is_not_yet_valid"]:
                self.lbl_cert_info.config(text=f"✗ Ainda não ativo (a partir de {info['valid_from']})", foreground="orange")
                messagebox.showwarning("Certificado", f"Certificado ainda não ativo (válido a partir de {info['valid_from']}).")
            else:
                self.lbl_cert_info.config(text=f"✓ Válido até {info['valid_until'][:10]}", foreground="green")
                self.log("SUCCESS", f"Certificado A1 válido ({info['subject_cn']}), expira em {info['valid_until']}.")
                messagebox.showinfo(
                    "Certificado Válido",
                    f"Certificado A1 Válido!\n\n"
                    f"Titular: {info['subject_cn']}\n"
                    f"Emissor: {info['issuer_cn']}\n"
                    f"Válido até: {info['valid_until']}",
                )
        except Exception as e:
            self.lbl_cert_info.config(text=f"✗ {e}", foreground="red")
            self.log("ERROR", f"Falha no certificado: {e}")
            messagebox.showerror("Erro no Certificado", str(e))

    def _on_key_changed(self, *args) -> None:
        raw = self.key_var.get().replace(" ", "").strip()
        count = len(raw)
        if count == 0:
            self.key_info_label.config(text="Digite a chave da NF-e", foreground="gray")
            return
        if count < 44:
            self.key_info_label.config(text=f"Digitando: {count}/44 dígitos", foreground="gray")
            return
        if count > 44:
            self.key_info_label.config(text=f"Chave longa demais ({count}/44 dígitos)", foreground="red")
            return

        val = validate_nfe_access_key(raw)
        mod = raw[20:22]
        is_cte = (mod in ("57", "67"))
        doc_tipo = "CT-e (Transporte)" if is_cte else "NF-e (Mercadoria)"
        btn_label = "📄 Gerar DACTE (PDF)" if is_cte else "📄 Gerar DANFE (PDF)"
        self.btn_generate_danfe.config(text=btn_label)

        if val.valid:
            uf = raw[:2]
            self.key_info_label.config(text=f"✓ Chave válida! UF: {uf} | {doc_tipo} (Mod {mod}) | DV conferido", foreground="green")
        else:
            self.key_info_label.config(text=f"✗ Inconsistente: {', '.join(val.errors)}", foreground="red")

    def refresh_status(self) -> None:
        try:
            summary = self.registry.get_status_summary()
            self.lbl_rate.config(text=f"{summary['queries_last_hour']} / {summary['max_queries_allowed']}")
            self.lbl_cache.config(text=f"{summary['total_cached_keys']} notas")
            self.lbl_next_slot.config(text=summary["next_slot_str"])

            if summary["is_blocked"]:
                self.lbl_block.config(
                    text=f"Bloqueado ({summary['block_reason']}) - Restam {summary['minutes_left']} min",
                    foreground="red",
                )
            else:
                self.lbl_block.config(text="Livre (Sem bloqueios)", foreground="green")
        except Exception:
            pass

    # --- PROCESSAMENTO INDIVIDUAL ---
    def _handle_dry_run(self) -> None:
        key = self.key_var.get().strip()
        cnpj = self.cnpj_var.get().strip()
        if not key:
            messagebox.showwarning("Aviso", "Informe a chave de acesso da NF-e.")
            return

        self.log("INFO", f"Executando validação local (dry-run) para a chave {key[:8]}...")
        result = search_nfe_xml(access_key=key, cnpj=cnpj or "00000000000000", cert_path="", cert_password="", dry_run=True, registry=self.registry)

        if result["status"] == "CACHE_HIT":
            self.log("SUCCESS", result["message"])
            self.last_downloaded_xml = result.get("content")
            self.last_downloaded_key = key
            self.btn_send_to_validator.config(state="normal")
            self.btn_generate_danfe.config(state="normal")
            messagebox.showinfo("Cache Local", result["message"])
        elif result["status"] == "DRY_RUN_READY":
            self.log("SUCCESS", result["message"])
            messagebox.showinfo("Validação OK", result["message"])
        else:
            self.log("WARN", result["message"])
            messagebox.showwarning("Aviso de Validação", result["message"])

        self.refresh_status()

    def _handle_search(self) -> None:
        key = self.key_var.get().strip()
        cnpj = self.cnpj_var.get().strip()
        cert = self.cert_var.get().strip()
        password = self.pass_var.get()
        is_homolog = (self.env_var.get() == "2")

        if not key or not cnpj or not cert:
            messagebox.showwarning("Aviso", "Preencha a Chave, CNPJ e selecione o Certificado A1.")
            return

        val = validate_nfe_access_key(key)
        if not val.valid:
            messagebox.showerror("Chave Inválida", f"A chave não atende às regras fiscais:\n{', '.join(val.errors)}")
            return

        # Validação estrita do Certificado antes de chamar a SEFAZ
        from core.certificate import inspect_certificate
        try:
            cert_info = inspect_certificate(cert, password)
            if cert_info["is_expired"]:
                self.lbl_cert_info.config(text=f"✗ EXPIRADO em {cert_info['valid_until']}", foreground="red")
                self.log("ERROR", f"Certificado Digital A1 ({cert_info['subject_cn']}) EXPIRADO desde {cert_info['valid_until']}.")
                messagebox.showerror(
                    "Certificado Expirado",
                    f"O Certificado Digital A1 ({cert_info['subject_cn']}) está EXPIRADO desde:\n{cert_info['valid_until']}\n\n"
                    "A consulta foi CANCELADA antes de chamar a SEFAZ para evitar penalidades e consumo indevido.",
                )
                return
            if cert_info["is_not_yet_valid"]:
                messagebox.showerror("Certificado Inativo", f"O Certificado Digital A1 ainda não está ativo (válido a partir de {cert_info['valid_from']}).")
                return
            self.lbl_cert_info.config(text=f"✓ Válido até {cert_info['valid_until'][:10]}", foreground="green")
        except Exception as e:
            self.lbl_cert_info.config(text=f"✗ {e}", foreground="red")
            self.log("ERROR", f"Falha na validação do certificado: {e}")
            messagebox.showerror("Erro no Certificado Digital", f"Não foi possível validar o Certificado Digital A1:\n\n{e}\n\nA consulta não foi iniciada.")
            return

        self.btn_search.config(state="disabled")
        self.progress.config(mode="indeterminate")
        self.progress.start(10)
        self.log("INFO", f"Iniciando consulta individual à SEFAZ ({'Homologação' if is_homolog else 'Produção'})...")

        def task():
            try:
                res = search_nfe_xml(
                    access_key=key,
                    cnpj=cnpj,
                    cert_path=cert,
                    cert_password=password,
                    is_homologation=is_homolog,
                    registry=self.registry,
                )
                self.after(0, lambda: self._on_individual_search_done(res))
            except Exception as e:
                self.after(0, lambda: self._on_individual_search_err(str(e)))

        threading.Thread(target=task, daemon=True).start()

    def _on_individual_search_done(self, result: dict) -> None:
        self.btn_search.config(state="normal")
        self.progress.stop()
        self.refresh_status()

        status = result.get("status")
        msg = result.get("message", "")
        if status in ("SUCCESS", "CACHE_HIT"):
            self.log("SUCCESS", msg)
            self.last_downloaded_xml = result.get("content")
            self.last_downloaded_key = result.get("access_key")
            self.btn_send_to_validator.config(state="normal")
            self.btn_generate_danfe.config(state="normal")

            from core.danfe_generator import detect_document_type
            doc_type = detect_document_type(self.last_downloaded_key or self.last_downloaded_xml or "")
            doc_name = "DACTE" if doc_type == "CTE" else "DANFE"
            full_name = "CT-e (Conhecimento de Transporte)" if doc_type == "CTE" else "NF-e (Nota Fiscal Eletrônica)"

            self.btn_generate_danfe.config(text=f"📄 Gerar {doc_name} (PDF)")

            # Pergunta ao usuário se deseja gerar o documento auxiliar imediatamente
            ask_danfe = messagebox.askyesno(
                "Consulta Concluída com Sucesso",
                f"{msg}\n\nDocumento identificado: {full_name}\nDeseja gerar o documento auxiliar {doc_name} em PDF agora?",
                icon="question",
            )
            if ask_danfe:
                self._generate_danfe()
        else:
            self.log("WARN", msg)
            messagebox.showinfo("Retorno SEFAZ", msg)

    def _on_individual_search_err(self, err_msg: str) -> None:
        self.btn_search.config(state="normal")
        self.progress.stop()
        self.refresh_status()
        self.log("ERROR", f"Falha: {err_msg}")
        messagebox.showerror("Erro", err_msg)

    def _send_to_validator(self) -> None:
        if self.last_downloaded_xml:
            self.on_xml_ready_for_validation(self.last_downloaded_xml, self.last_downloaded_key or "")

    def _generate_danfe(self) -> None:
        if not self.last_downloaded_xml:
            messagebox.showwarning("Aviso", "Nenhum XML disponível para gerar o documento auxiliar.")
            return

        from core.danfe_generator import detect_document_type, generate_fiscal_document_pdf, open_pdf_file
        doc_type = detect_document_type(self.last_downloaded_key or self.last_downloaded_xml or "")
        doc_name = "DACTE" if doc_type == "CTE" else "DANFE"
        default_filename = f"{doc_name}_{self.last_downloaded_key or 'doc'}.pdf"

        filepath = filedialog.asksaveasfilename(
            title=f"Salvar {doc_name} em PDF",
            initialfile=default_filename,
            defaultextension=".pdf",
            filetypes=[("Documentos PDF (*.pdf)", "*.pdf"), ("Todos os arquivos", "*.*")],
        )
        if filepath:
            try:
                _, out_path = generate_fiscal_document_pdf(self.last_downloaded_xml, output_pdf_path=filepath)
                self.log("SUCCESS", f"{doc_name} em PDF gerado: {out_path}")
                open_now = messagebox.askyesno(
                    f"{doc_name} Gerado com Sucesso",
                    f"{doc_name} em PDF gerado com sucesso!\nSalvo em:\n{out_path}\n\nDeseja abrir o arquivo PDF agora?",
                )
                if open_now:
                    open_pdf_file(out_path)
            except Exception as e:
                self.log("ERROR", f"Falha ao gerar {doc_name}: {e}")
                messagebox.showerror(f"Erro ao Gerar {doc_name}", f"Não foi possível gerar o {doc_name} em PDF:\n{e}")

    # --- PROCESSAMENTO EM LOTE ---
    def _import_batch_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Selecione o arquivo com as Chaves de Acesso",
            filetypes=[("Arquivos de Texto e CSV", "*.txt *.csv"), ("Todos os arquivos", "*.*")],
        )
        if filename:
            try:
                keys = extract_keys_from_file(filename)
                self._load_batch_keys(keys, source_name=Path(filename).name)
            except Exception as e:
                messagebox.showerror("Erro ao Ler Arquivo", f"Não foi possível extrair chaves:\n{e}")

    def _open_paste_dialog(self) -> None:
        top = tk.Toplevel(self)
        top.title("Colar Lista de Chaves de Acesso")
        top.geometry("600x420")
        top.transient(self)
        top.grab_set()

        ttk.Label(top, text="Cole as chaves de acesso abaixo (uma por linha ou separadas por vírgula):", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(10, 4))

        txt_area = ScrolledText(top, wrap="word", font=("Consolas", 9))
        txt_area.pack(fill="both", expand=True, padx=10, pady=4)

        btn_frame = ttk.Frame(top)
        btn_frame.pack(fill="x", padx=10, pady=10)

        def on_confirm():
            raw = txt_area.get("1.0", "end")
            keys = extract_keys_from_text(raw)
            if not keys:
                messagebox.showwarning("Aviso", "Nenhuma chave de 44 dígitos válida foi identificada no texto informado.")
                return
            top.destroy()
            self._load_batch_keys(keys, source_name="Texto Colado")

        ttk.Button(btn_frame, text="Confirmar e Importar", command=on_confirm).pack(side="right", padx=(6, 0))
        ttk.Button(btn_frame, text="Cancelar", command=top.destroy).pack(side="right")

    def _load_batch_keys(self, keys: list[str], source_name: str = "") -> None:
        if not keys:
            messagebox.showwarning("Aviso", "Nenhuma chave localizada para processamento.")
            return

        self.batch_manager = BatchQueryManager(
            registry=self.registry,
            cnpj=self.cnpj_var.get().strip(),
            cert_path=self.cert_var.get().strip(),
            cert_password=self.pass_var.get(),
            is_homologation=(self.env_var.get() == "2"),
        )
        self.batch_items = self.batch_manager.load_keys(keys)
        self._populate_batch_tree()

        in_cache = sum(1 for it in self.batch_items if it.status == "EM_CACHE")
        pending = sum(1 for it in self.batch_items if it.status == "PENDENTE")
        invalid = sum(1 for it in self.batch_items if it.status == "ERRO")

        msg = f"{len(self.batch_items)} chaves carregadas ({source_name}): {in_cache} já em cache | {pending} pendentes SEFAZ | {invalid} inválidas"
        self.lbl_batch_summary.config(text=msg)
        self.log("INFO", msg)

    def _populate_batch_tree(self) -> None:
        for row in self.tree_batch.get_children():
            self.tree_batch.delete(row)

        for i, item in enumerate(self.batch_items):
            self.tree_batch.insert("", "end", iid=str(i), values=(item.access_key, item.status, item.source, item.message))

    def _clear_batch_list(self) -> None:
        for row in self.tree_batch.get_children():
            self.tree_batch.delete(row)
        self.batch_items = []
        self.batch_manager = None
        self.lbl_batch_summary.config(text="Nenhuma lista de chaves carregada.")

    def _start_batch_processing(self) -> None:
        if not self.batch_items:
            messagebox.showwarning("Aviso", "Carregue uma lista de chaves antes de iniciar o lote.")
            return

        cnpj = self.cnpj_var.get().strip()
        cert = self.cert_var.get().strip()
        password = self.pass_var.get()
        if not cnpj or not cert:
            messagebox.showwarning("Aviso", "Informe o CNPJ do Consulente e o Certificado A1 antes de iniciar o lote.")
            return

        # Reativa itens que estavam pausados ou bloqueados para continuar exatamente de onde parou
        reactivated = self.batch_manager.reset_paused_or_blocked()
        if reactivated > 0:
            self._populate_batch_tree()
            self.log("INFO", f"Retomando esteira: {reactivated} chaves reativadas para continuar de onde parou.")

        pending_count = sum(1 for it in self.batch_items if it.status == "PENDENTE")
        if pending_count == 0:
            messagebox.showinfo("Lote Concluído", "Todas as chaves da lista já estão resolvidas (em cache local ou concluídas com sucesso).")
            return

        # Validação estrita do Certificado antes de iniciar a fila do lote
        from core.certificate import inspect_certificate
        try:
            cert_info = inspect_certificate(cert, password)
            if cert_info["is_expired"]:
                self.lbl_cert_info.config(text=f"✗ EXPIRADO em {cert_info['valid_until']}", foreground="red")
                self.log("ERROR", f"Certificado Digital A1 ({cert_info['subject_cn']}) EXPIRADO desde {cert_info['valid_until']}.")
                messagebox.showerror(
                    "Certificado Expirado",
                    f"O Certificado Digital A1 ({cert_info['subject_cn']}) está EXPIRADO desde:\n{cert_info['valid_until']}\n\n"
                    "O processamento em lote foi CANCELADO antes de chamar a SEFAZ.",
                )
                return
            if cert_info["is_not_yet_valid"]:
                messagebox.showerror("Certificado Inativo", f"O Certificado Digital A1 ainda não está ativo (válido a partir de {cert_info['valid_from']}).")
                return
            self.lbl_cert_info.config(text=f"✓ Válido até {cert_info['valid_until'][:10]}", foreground="green")
        except Exception as e:
            self.lbl_cert_info.config(text=f"✗ {e}", foreground="red")
            self.log("ERROR", f"Falha na validação do certificado: {e}")
            messagebox.showerror("Erro no Certificado Digital", f"Não foi possível validar o Certificado Digital A1:\n\n{e}\n\nO lote não foi iniciado.")
            return

        # Atualiza parâmetros no batch_manager
        self.batch_manager.cnpj = cnpj
        self.batch_manager.cert_path = cert
        self.batch_manager.cert_password = password
        self.batch_manager.is_homologation = (self.env_var.get() == "2")

        auto_wait = self.batch_auto_wait_var.get()

        self.btn_start_batch.config(state="disabled")
        self.btn_stop_batch.config(state="normal")
        self.progress.config(mode="determinate", maximum=len(self.batch_items), value=0)

        mode_desc = "com Piloto Automático ativado (aguardará liberação de cota sozinho)" if auto_wait else "modo padrão"
        self.log("INFO", f"Iniciando fila em lote ({mode_desc}) com {pending_count} chaves pendentes para consulta na SEFAZ...")

        def update_item_ui(index: int, item: BatchQueryItem):
            self.after(0, lambda: self._update_batch_row(index, item))

        def update_progress_ui(processed: int, total: int):
            self.after(0, lambda: self.progress.config(value=processed))

        def update_waiting_ui(sec: int, msg: str):
            if sec > 0:
                mins = sec // 60
                secs = sec % 60
                self.after(0, lambda: self.lbl_batch_countdown.config(text=f"⏳ Cota 15/h atingida. Retoma em {mins:02d}:{secs:02d}"))
            else:
                self.after(0, lambda: self.lbl_batch_countdown.config(text=""))

        def task():
            summary = self.batch_manager.process(
                on_item_updated=update_item_ui,
                on_progress=update_progress_ui,
                auto_wait_quota=auto_wait,
                on_waiting=update_waiting_ui,
            )
            self.after(0, lambda: self._on_batch_finished(summary))

        threading.Thread(target=task, daemon=True).start()

    def _update_batch_row(self, index: int, item: BatchQueryItem) -> None:
        iid = str(index)
        if self.tree_batch.exists(iid):
            self.tree_batch.item(iid, values=(item.access_key, item.status, item.source, item.message))
            self.tree_batch.see(iid)

    def _stop_batch_processing(self) -> None:
        if self.batch_manager:
            self.batch_manager.stop()
            self.log("WARN", "Solicitação de parada enviada ao processador de lote.")
            self.lbl_batch_countdown.config(text="⏹ Pausando...")
            self.btn_stop_batch.config(state="disabled")

    def _on_batch_finished(self, summary: dict) -> None:
        self.btn_start_batch.config(state="normal")
        self.btn_stop_batch.config(state="disabled")
        self.lbl_batch_countdown.config(text="")
        self.refresh_status()

        in_cache = sum(1 for it in self.batch_items if it.status in ("EM_CACHE", "CONCLUIDO"))
        pending = sum(1 for it in self.batch_items if it.status in ("PENDENTE", "PAUSADO", "BLOQUEADO"))
        errors = sum(1 for it in self.batch_items if it.status == "ERRO")
        self.lbl_batch_summary.config(
            text=f"Lote: {len(self.batch_items)} chaves | {in_cache} resolvidas (cache/SEFAZ) | {pending} pendentes | {errors} erros"
        )

        msg = (
            f"Processamento de Lote Concluído!\n\n"
            f"• Total de chaves na lista: {summary['total']}\n"
            f"• Resgatadas do Cache Local: {summary['cache_hits']}\n"
            f"• Baixadas da SEFAZ: {summary['downloaded']}\n"
            f"• Erros / Inconsistências: {summary['errors']}\n"
            f"• Pausadas / Aguardando cota: {summary['rate_limited']}"
        )
        if summary.get("stopped"):
            msg += "\n\n💡 O lote foi pausado. Para continuar de onde parou, basta clicar em 'Iniciar / Continuar Lote'!"
        self.log("SUCCESS" if summary["errors"] == 0 else "WARN", f"Lote finalizado: {summary['downloaded']} baixadas, {summary['cache_hits']} cache, {summary['errors']} erros.")
        messagebox.showinfo("Resultado do Lote", msg)

    def _on_batch_row_double_click(self, event) -> None:
        selected = self.tree_batch.selection()
        if not selected:
            return
        idx = int(selected[0])
        item = self.batch_items[idx]
        if item.file_path and Path(item.file_path).exists():
            xml_content = Path(item.file_path).read_text(encoding="utf-8")
            self.on_xml_ready_for_validation(xml_content, item.access_key)
        else:
            messagebox.showinfo("Detalhes da Chave", f"Chave: {item.access_key}\nStatus: {item.status}\nOrigem: {item.source}\nMensagem: {item.message}")

    # =========================================================================
    # --- SUB-ABA C: SINCRONIZAÇÃO EM LOTE POR NSU (distNSU) ---
    # =========================================================================

    def _update_nsu_cursor_display(self) -> None:
        raw_cnpj = self.cnpj_var.get()
        clean_cnpj = "".join(filter(str.isdigit, raw_cnpj))
        if len(clean_cnpj) == 14:
            state = self.registry.get_nsu_state(clean_cnpj)
            self.nsu_var.set(state.get("ult_nsu", "000000000000000"))
            self.lbl_nsu_summary.config(
                text=f"Status: Pronto | Último NSU: {state.get('ult_nsu', '000000000000000')} | "
                     f"Maior NSU: {state.get('max_nsu', '000000000000000')} | Docs na tabela: {len(self.nsu_items)}"
            )

    def _clear_nsu_list(self) -> None:
        self.tree_nsu.delete(*self.tree_nsu.get_children())
        self.nsu_items.clear()
        self.lbl_nsu_summary.config(
            text=f"Status: Limpo | Cursor NSU: {self.nsu_var.get()} | Docs na tabela: 0"
        )
        self.log("INFO", "Tabela de sincronização NSU limpa.")

    def _reset_nsu(self) -> None:
        clean_cnpj = "".join(filter(str.isdigit, self.cnpj_var.get()))
        if len(clean_cnpj) != 14:
            messagebox.showwarning("Aviso", "Informe um CNPJ válido com 14 dígitos antes de resetar o NSU.")
            return

        confirm = messagebox.askyesno(
            "Confirmar Reset de NSU",
            "Deseja realmente redefinir o cursor NSU para zero (000000000000000)?\n\n"
            "Isso fará com que a SEFAZ retorne os documentos fiscais desde o início dos registros retidos (últimos 90 dias).",
        )
        if confirm:
            self.registry.reset_nsu(clean_cnpj)
            self.nsu_var.set("000000000000000")
            self.lbl_nsu_summary.config(
                text="Status: NSU resetado para 0 | Pronto para iniciar sincronização completa."
            )
            self.log("WARN", f"Cursor NSU resetado para zero para o CNPJ {clean_cnpj}.")

    def _start_nsu_sync(self) -> None:
        clean_cnpj = "".join(filter(str.isdigit, self.cnpj_var.get()))
        if len(clean_cnpj) != 14:
            messagebox.showerror("CNPJ Inválido", "Informe um CNPJ válido com 14 dígitos nas credenciais.")
            return

        cert = self.cert_var.get().strip()
        pwd = self.pass_var.get()
        if not cert or not Path(cert).exists():
            messagebox.showerror("Certificado Ausente", "Selecione o arquivo do certificado digital A1 (.pfx/.p12).")
            return

        from core.certificate import inspect_certificate
        try:
            cert_info = inspect_certificate(cert, pwd)
            if cert_info["is_expired"]:
                messagebox.showerror(
                    "Certificado Expirado",
                    f"O certificado A1 ({cert_info['subject_cn']}) expirou em {cert_info['valid_until']}.\n"
                    "A SEFAZ rejeitará a sincronização.",
                )
                return
            if cert_info["is_not_yet_valid"]:
                messagebox.showerror(
                    "Certificado Inativo",
                    f"O certificado ainda não está ativo (válido a partir de {cert_info['valid_from']}).",
                )
                return
            self.lbl_cert_info.config(text=f"✓ Válido até {cert_info['valid_until'][:10]}", foreground="green")
        except Exception as e:
            messagebox.showerror("Erro no Certificado", f"Falha ao validar certificado A1: {e}")
            return

        start_nsu_str = self.nsu_var.get().strip()
        if not start_nsu_str.isdigit():
            messagebox.showerror("NSU Inválido", "O valor do último NSU deve conter apenas números.")
            return

        selected_uf = self.nsu_uf_var.get()
        c_uf_autor = UF_IBGE_MAP.get(selected_uf, "35")
        is_homologation = (self.env_var.get() == "2")

        self.btn_start_nsu.config(state="disabled")
        self.btn_stop_nsu.config(state="normal")
        self.btn_reset_nsu.config(state="disabled")
        self.progress.config(mode="indeterminate")
        self.progress.start(10)

        self.log("INFO", f"Iniciando Sincronização por NSU (UF Autorizadora: {selected_uf}, cUFAutor: {c_uf_autor}, ultNSU: {start_nsu_str})...")

        self.nsu_manager = NsuSyncManager(
            registry=self.registry,
            cnpj=clean_cnpj,
            cert_path=cert,
            cert_password=pwd,
            c_uf_autor=c_uf_autor,
            is_homologation=is_homologation,
            delay_seconds=1.5,
        )

        def on_batch_start_ui(cur_nsu: str, batch_num: int):
            self.after(0, lambda: self._on_nsu_batch_started(cur_nsu, batch_num))

        def on_doc_ui(item: NsuDocumentItem):
            self.after(0, lambda: self._on_nsu_item_received(item))

        def on_progress_ui(cur_nsu: str, max_nsu: str, total_docs: int):
            self.after(0, lambda: self._on_nsu_progress(cur_nsu, max_nsu, total_docs))

        def task():
            summary = self.nsu_manager.sync(
                start_nsu=start_nsu_str,
                on_batch_start=on_batch_start_ui,
                on_doc_received=on_doc_ui,
                on_progress=on_progress_ui,
            )
            self.after(0, lambda: self._on_nsu_finished(summary))

        threading.Thread(target=task, daemon=True).start()

    def _stop_nsu_sync(self) -> None:
        if self.nsu_manager:
            self.nsu_manager.stop()
            self.log("WARN", "Solicitação de parada enviada à sincronização por NSU.")
            self.btn_stop_nsu.config(state="disabled")

    def _on_nsu_batch_started(self, cur_nsu: str, batch_num: int) -> None:
        self.log("INFO", f"Requisitando pacote #{batch_num} da SEFAZ (NSU > {cur_nsu})...")

    def _on_nsu_item_received(self, item: NsuDocumentItem) -> None:
        idx = len(self.nsu_items)
        self.nsu_items.append(item)
        iid = str(idx)

        file_status = "Salvo em disco" if item.file_path else ("Resumo" if "Resumo" in item.doc_type else item.status)
        formatted_val = item.total_value
        try:
            val_float = float(item.total_value)
            formatted_val = f"{val_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except ValueError:
            pass

        self.tree_nsu.insert(
            "",
            "end",
            iid=iid,
            values=(
                item.nsu,
                item.doc_type,
                item.access_key,
                item.emit_name[:25] if item.emit_name else "-",
                formatted_val,
                item.issue_date[:10] if len(item.issue_date) >= 10 else item.issue_date,
                file_status,
            ),
        )
        self.tree_nsu.see(iid)

    def _on_nsu_progress(self, ult_nsu: str, max_nsu: str, total_docs: int) -> None:
        self.nsu_var.set(ult_nsu)
        self.lbl_nsu_summary.config(
            text=f"Status: Sincronizando... | Cursor NSU: {ult_nsu} | Maior NSU: {max_nsu} | Documentos: {total_docs}"
        )

    def _on_nsu_finished(self, summary: dict) -> None:
        self.progress.stop()
        self.progress.config(mode="determinate", value=0)
        self.btn_start_nsu.config(state="normal")
        self.btn_stop_nsu.config(state="disabled")
        self.btn_reset_nsu.config(state="normal")
        self.refresh_status()

        ult_nsu = summary.get("ult_nsu", self.nsu_var.get())
        max_nsu = summary.get("max_nsu", "000000000000000")
        self.nsu_var.set(ult_nsu)

        self.lbl_nsu_summary.config(
            text=f"Status: Finalizado (cStat {summary.get('last_c_stat', '-')}) | "
                 f"Último NSU: {ult_nsu} | Maior NSU: {max_nsu} | "
                 f"Baixados: {summary.get('total_docs', 0)} ({summary.get('full_xmls_saved', 0)} completos salvos)"
        )

        log_msg = (
            f"Sincronização NSU concluída: {summary.get('total_docs', 0)} documentos processados "
            f"({summary.get('full_xmls_saved', 0)} XMLs completos gravados em sefaz_data/xmls). "
            f"Cursor atualizado para {ult_nsu}."
        )
        self.log("SUCCESS" if summary.get("error_message") is None else "WARN", log_msg)

        msg = (
            f"Sincronização por NSU Concluída!\n\n"
            f"• Lotes consultados: {summary.get('batches_processed', 0)}\n"
            f"• Total de documentos retornados: {summary.get('total_docs', 0)}\n"
            f"• XMLs completos salvos em disco: {summary.get('full_xmls_saved', 0)}\n"
            f"• Resumos de notas: {summary.get('resumos_count', 0)}\n"
            f"• Eventos / Cancelamentos: {summary.get('eventos_count', 0)}\n"
            f"• Cursor final (ultNSU): {ult_nsu}\n"
            f"• Maior NSU na SEFAZ (maxNSU): {max_nsu}\n"
            f"• Status SEFAZ: {summary.get('last_c_stat', '-')} - {summary.get('last_x_motivo', '-')}"
        )
        messagebox.showinfo("Sincronização por NSU", msg)

    def _on_nsu_row_double_click(self, event) -> None:
        selected = self.tree_nsu.selection()
        if not selected:
            return
        idx = int(selected[0])
        if idx >= len(self.nsu_items):
            return
        item = self.nsu_items[idx]

        if item.file_path and Path(item.file_path).exists():
            xml_content = Path(item.file_path).read_text(encoding="utf-8")
            self.on_xml_ready_for_validation(xml_content, item.access_key)
        elif item.xml_content and item.doc_type in ("NF-e (Completa)", "CT-e (Completo)"):
            self.on_xml_ready_for_validation(item.xml_content, item.access_key)
        else:
            messagebox.showinfo(
                "Detalhes do Documento NSU",
                f"NSU: {item.nsu}\n"
                f"Tipo: {item.doc_type}\n"
                f"Chave de Acesso: {item.access_key}\n"
                f"Emitente: {item.emit_name} ({item.emit_doc})\n"
                f"Valor Total: R$ {item.total_value}\n"
                f"Data: {item.issue_date}\n\n"
                "Nota: Este documento é um resumo ou evento SEFAZ e não possui o XML completo da nota.",
            )
