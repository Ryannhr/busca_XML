"""
Janela Principal da Interface Gráfica (Tkinter) do SEFAZ DF-e Client.
"""

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from core.registry import SefazLocalRegistry
from .tab_query import QueryTab
from .tab_validator import ValidatorTab


class SefazApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SEFAZ DF-e Client & Validador de XML NF-e")
        self.geometry("1020x720")
        self.minsize(860, 600)

        self._configure_styles()

        # Registro local de dados
        self.registry = SefazLocalRegistry()

        # Container principal com abas
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # Aba 1: Consulta & Download SEFAZ
        self.query_tab = QueryTab(
            self.notebook,
            registry=self.registry,
            on_xml_ready_for_validation=self.transfer_xml_to_validator,
        )
        self.notebook.add(self.query_tab, text="   Consulta e Download SEFAZ  ")

        # Aba 2: Validação e Inspeção de XML
        self.validator_tab = ValidatorTab(self.notebook)
        self.notebook.add(self.validator_tab, text="   Validador e Inspetor de XML  ")

        # Barra de status no rodapé
        self._build_statusbar()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=[12, 6])
        style.configure("TButton", font=("Segoe UI", 9), padding=5)
        style.configure("TLabel", font=("Segoe UI", 9))
        style.configure("TLabelframe.Label", font=("Segoe UI", 9, "bold"), foreground="#1a73e8")

    def _build_statusbar(self) -> None:
        statusbar = ttk.Frame(self, relief="sunken", padding=(8, 3))
        statusbar.pack(side="bottom", fill="x")

        lbl_engine = ttk.Label(statusbar, text="SEFAZ SVRS / NFeDistribuicaoDFe v1.01 | mTLS A1", font=("Segoe UI", 8), foreground="gray")
        lbl_engine.pack(side="left")

        lbl_ver = ttk.Label(statusbar, text="Versão Modular 2.0 | Python Tkinter", font=("Segoe UI", 8), foreground="gray")
        lbl_ver.pack(side="right")

    def transfer_xml_to_validator(self, xml_content: str, access_key: str = "") -> None:
        """Transfere o XML baixado na consulta diretamente para a aba de validação."""
        self.validator_tab.load_xml_content(xml_content, key_hint=access_key)
        self.notebook.select(self.validator_tab)


def launch_app() -> None:
    app = SefazApp()
    app.mainloop()


if __name__ == "__main__":
    launch_app()

