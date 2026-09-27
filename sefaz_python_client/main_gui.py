"""
Ponto de entrada direto para a Interface Gráfica Tkinter do SEFAZ DF-e Client.
"""

import sys
from pathlib import Path

_CURRENT_DIR = Path(__file__).resolve().parent
if str(_CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CURRENT_DIR))

from gui.app import launch_app

if __name__ == "__main__":
    launch_app()

