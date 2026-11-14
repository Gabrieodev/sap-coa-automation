"""Lista as janelas do Windows que aparecem enquanto você anexa um arquivo MANUALMENTE no SAP.

Uso (Windows, SAP GUI aberto e logado):
  1. python scripts\\listar_janelas.py            (observa por 60 s; ou: ... 120)
  2. No SAP: ME22N > abra um pedido > Serviços para objeto > Criar > Criar anexo > escolha o arquivo
     > clique em Permitir (se o aviso de segurança aparecer).
  3. Me envie a saída: ela mostra o título e a classe EXATOS de cada janela e os botões de cada uma,
     que é o que o robô usa para achar 'Abrir' e 'Permitir' (src/sap/dialogo_arquivo.py).
Não altera nada: só observa.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.console import usar_utf8  # noqa: E402


def main() -> int:
    usar_utf8()
    segundos = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    try:
        from pywinauto import Desktop
    except ImportError:
        print("pywinauto não instalado (pip install pywinauto). Este script só roda no Windows.")
        return 2
    desktop = Desktop(backend="win32")
    vistas: set[int] = set()
    inicio = time.monotonic()
    print(f"Observando janelas por {segundos}s... faça o anexo manualmente agora.\n")
    while time.monotonic() - inicio < segundos:
        for w in desktop.windows(visible_only=True):
            if w.handle in vistas:
                continue
            vistas.add(w.handle)
            titulo = (w.window_text() or "").strip()
            if not titulo:
                continue
            try:
                filhos = [(c.class_name(), (c.window_text() or "").strip()) for c in w.children()]
            except Exception:
                filhos = []
            botoes = [t for cls, t in filhos if cls == "Button" and t]
            print(f"[{time.monotonic() - inicio:5.1f}s] classe={w.class_name()!r} título={titulo!r}")
            if botoes:
                print(f"           botões: {botoes}")
        time.sleep(0.3)
    print("\nFim. Procure na saída as janelas 'Abrir' e a de segurança do SAP GUI (botão 'Permitir').")
    return 0


if __name__ == "__main__":
    sys.exit(main())
