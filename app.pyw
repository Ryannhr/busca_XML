"""
Lançador silencioso (sem janela preta de console) para Windows.
Basta dar dois cliques neste arquivo no Windows Explorer.
"""

import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent / "sefaz_python_client"
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from gui.app import launch_app

if __name__ == "__main__":
    launch_app()

