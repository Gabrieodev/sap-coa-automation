import csv
import logging
import sys
from datetime import datetime
from pathlib import Path


def configurar_logger(logs_dir: Path, nome: str = "coa") -> tuple[logging.Logger, str]:
    """Cria log em arquivo (logs/execucao_<ts>.log) + console. Devolve (logger, timestamp)."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log = logging.getLogger(f"{nome}.{ts}")
    log.setLevel(logging.DEBUG)
    log.propagate = False
    encerrar_logger(log)  # mesmo nome (2 execuções no mesmo segundo): não acumula handlers
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", "%Y-%m-%d %H:%M:%S")

    arq = logging.FileHandler(logs_dir / f"execucao_{ts}.log", encoding="utf-8")
    arq.setFormatter(fmt)
    arq.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.setLevel(logging.INFO)

    log.addHandler(arq)
    log.addHandler(console)
    return log, ts


def encerrar_logger(log: logging.Logger) -> None:
    """Fecha e remove os handlers. Sem isso o arquivo de log fica aberto e, no Windows, não pode
    ser apagado/movido enquanto o processo estiver vivo."""
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()


def gravar_relatorio_csv(logs_dir: Path, ts: str, resultados) -> Path:
    """Relatório por pedido. Separador ';' e BOM para abrir direto no Excel BR."""
    caminho = logs_dir / f"relatorio_{ts}.csv"
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["linha", "pedido", "processo", "status", "mensagem",
                    "anexados", "ja_existiam", "duracao_s"])
        for r in resultados:
            w.writerow([r.item.linha, r.item.pedido, r.item.processo, r.status, r.mensagem,
                        " | ".join(r.anexados), " | ".join(r.ja_existiam),
                        f"{r.duracao_s:.1f}"])
    return caminho
