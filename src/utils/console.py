"""Console em UTF-8, mesmo quando a saída é redirecionada (arquivo, pipe, Agendador de Tarefas)."""
import sys


def usar_utf8() -> None:
    """No Windows, saída redirecionada usa cp1252 e quebra com símbolos como ✓ e →.
    Troca para UTF-8 (com substituição de segurança) sem depender de configuração do PC."""
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # fluxo sem reconfigure (ex.: capturado por teste): nada a fazer
