"""Valida, passo a passo e com SAP real, se os seletores de src/sap/seletores.py batem.

Uso:  python scripts/diagnostico_sap.py 4500001001
Não anexa nada. Para cada etapa imprime OK ou o erro, e no fim mostra as colunas da
lista de anexos (para você ajustar COA_COLUNA_TITULO_ANEXOS / config.coluna_titulo_anexos).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config as cfg_mod
from src.sap import seletores as sel
from src.sap.dialogo_arquivo import DialogoArquivo
from src.sap.navegacao import SapNavigation
from src.sap.pedidos import SapPedidos


def passo(nome, fn):
    try:
        r = fn()
        print(f"[OK]    {nome}" + (f" -> {r}" if r not in (None, "") else ""))
        return r
    except Exception as e:
        print(f"[FALHA] {nome}: {type(e).__name__}: {e}")
        return None


def main():
    if len(sys.argv) < 2:
        sys.exit("Informe um número de pedido real: python scripts/diagnostico_sap.py <pedido>")
    pedido = sys.argv[1]
    cfg = cfg_mod.carregar()

    nav = passo("Conectar ao SAP e obter sessão", SapNavigation)
    if not nav:
        return
    sap = SapPedidos(nav, DialogoArquivo(), cfg.transacao, cfg.timeout_sap, cfg.coluna_titulo_anexos)

    passo(f"Abrir pedido {pedido} na {cfg.transacao}", lambda: sap.abrir_pedido(pedido))
    passo("Barra de status", nav.status_barra)
    passo("Existe a barra de Serviços para objeto?", lambda: nav.existe(sel.GOS_BARRA))
    anexos = passo("Listar anexos existentes", sap.listar_anexos)

    # Lista de anexos: mostra as colunas reais do grid, se ele estiver acessível
    try:
        nav.clicar_menu_contexto(sel.GOS_BARRA, sel.GOS_MENU, sel.GOS_LISTA_ANEXOS)
        nav.aguardar(cfg.timeout_sap)
        grid = nav.obter(sel.GRID_ANEXOS)
        print("[INFO]  Colunas do grid de anexos:", [str(c) for c in grid.ColumnOrder])
        for i in range(min(int(grid.RowCount), 3)):
            print("[INFO]  linha", i, {str(c): str(grid.GetCellValue(i, c)) for c in grid.ColumnOrder})
    except Exception as e:
        print(f"[FALHA] Inspecionar grid de anexos ({sel.GRID_ANEXOS}): {type(e).__name__}: {e}")
        print("        -> grave o passo manual com o gravador de scripts e ajuste seletores.py")
    finally:
        sap.limpar_popups()
    print("\nAnexos lidos:", anexos)


if __name__ == "__main__":
    main()
