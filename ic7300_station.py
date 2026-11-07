"""Ponto de entrada do executável (PyInstaller)."""
import sys

from ic7300.main import main

if __name__ == "__main__":
    sys.exit(main())
