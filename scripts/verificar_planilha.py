r"""Descobre se gravar na planilha via openpyxl faria perder algo (Power Query, slicers etc.).

Uso:  python scripts\verificar_planilha.py "C:\caminho\DATA BASE.xlsx"
Trabalha numa CÓPIA temporária; o arquivo original não é modificado.
Código de saída: 0 = sem perdas graves | 1 = perderia recursos importantes
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.console import usar_utf8
from src.utils.verificar_planilha import analisar


def main() -> int:
    usar_utf8()
    if len(sys.argv) < 2:
        sys.exit('Informe o arquivo: python scripts\\verificar_planilha.py "C:\\...\\DATA BASE.xlsx"')
    rel = analisar(Path(sys.argv[1]))
    print(rel.texto())
    return 1 if rel.tem_perda_grave else 0


if __name__ == "__main__":
    sys.exit(main())
