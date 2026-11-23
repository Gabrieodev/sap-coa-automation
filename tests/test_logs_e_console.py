"""Regressões vistas no Windows: arquivo de log preso e console cp1252 quebrando com ✓/→."""
import logging
import os
import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook

import main as main_mod
from src.utils.logger import configurar_logger, encerrar_logger

RAIZ = Path(__file__).resolve().parents[1]


def test_logger_chamado_duas_vezes_no_mesmo_segundo_nao_duplica_linhas(tmp_path):
    a, ts = configurar_logger(tmp_path)
    b, ts2 = configurar_logger(tmp_path)
    try:
        if ts == ts2:                      # mesmo nome de logger
            assert len(b.handlers) == 2    # arquivo + console, e não 4
    finally:
        encerrar_logger(a); encerrar_logger(b)


def test_encerrar_logger_fecha_o_arquivo(tmp_path):
    log, ts = configurar_logger(tmp_path)
    log.info("oi")
    arquivo = next(h for h in log.handlers if isinstance(h, logging.FileHandler))
    encerrar_logger(log)
    assert log.handlers == [] and arquivo.stream is None   # stream None = arquivo fechado
    (tmp_path / f"execucao_{ts}.log").unlink()             # no Windows isto falhava


def test_main_nao_deixa_logger_aberto(tmp_path, monkeypatch):
    wb = Workbook(); wb.active.append(["PROCESSO", "PEDIDO SAP"]); wb.save(tmp_path / "b.xlsx")
    for k, v in {"COA_PLANILHA": tmp_path / "b.xlsx", "COA_RAIZ_ARQUIVOS": tmp_path / "sp",
                 "COA_LOGS_DIR": tmp_path / "logs", "COA_ARQUIVO_ESTADO": tmp_path / "e.csv"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado"])
    assert main_mod.main() == 0
    abertos = [n for n, lg in logging.root.manager.loggerDict.items()
               if n.startswith("coa.") and isinstance(lg, logging.Logger) and lg.handlers]
    assert abertos == []


def test_script_nao_quebra_com_console_cp1252(tmp_path):
    """Simula o Windows com saída redirecionada: stdout em cp1252 não tem ✓ nem →."""
    wb = Workbook(); wb.active.append(["PROCESSO", "PEDIDO SAP"]); wb.save(tmp_path / "ok.xlsx")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    r = subprocess.run([sys.executable, str(RAIZ / "scripts" / "verificar_planilha.py"),
                        str(tmp_path / "ok.xlsx")], capture_output=True, cwd=RAIZ, env=env)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]
    assert "UnicodeEncodeError" not in r.stderr.decode("utf-8", "replace")


# ------------------------------------------------------------------ trava anti-execução-dupla
import os as _os
import time as _time

import pytest

from src.utils.trava import ExecucaoEmAndamentoError, TravaExecucao


def test_trava_impede_segunda_execucao_e_libera_ao_sair(tmp_path):
    a = TravaExecucao(tmp_path / "robo.lock")
    a.adquirir()
    with pytest.raises(ExecucaoEmAndamentoError, match="em andamento"):
        TravaExecucao(tmp_path / "robo.lock").adquirir()
    a.liberar()
    assert not (tmp_path / "robo.lock").exists()
    TravaExecucao(tmp_path / "robo.lock").adquirir()           # liberada: outra pode entrar


def test_trava_abandonada_e_retomada(tmp_path):
    lock = tmp_path / "robo.lock"; lock.write_text("pid=1 inicio=ontem")
    antigo = _time.time() - 5 * 3600
    _os.utime(lock, (antigo, antigo))                          # 5 h parada, validade 3 h
    t = TravaExecucao(lock, validade_horas=3); t.adquirir()
    assert "pid=" in lock.read_text(); t.liberar()


def test_liberar_nao_apaga_trava_de_outro(tmp_path):
    lock = tmp_path / "robo.lock"; lock.write_text("pid=1 de outro robô")
    TravaExecucao(lock).liberar()
    assert lock.exists()


def _ambiente(tmp_path, monkeypatch):
    wb = Workbook(); wb.active.append(["PROCESSO", "PEDIDO SAP"]); wb.save(tmp_path / "b.xlsx")
    for k, v in {"COA_PLANILHA": tmp_path / "b.xlsx", "COA_RAIZ_ARQUIVOS": tmp_path / "sp",
                 "COA_LOGS_DIR": tmp_path / "logs", "COA_ARQUIVO_ESTADO": tmp_path / "e.csv"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado"])


def test_main_com_outra_execucao_em_andamento_sai_com_3(tmp_path, monkeypatch):
    _ambiente(tmp_path, monkeypatch)
    (tmp_path / "robo.lock").write_text("pid=999 inicio=agora")
    assert main_mod.main() == 3
    assert (tmp_path / "robo.lock").exists()                   # a trava alheia não é apagada


def test_main_libera_a_trava_ao_terminar(tmp_path, monkeypatch):
    _ambiente(tmp_path, monkeypatch)
    assert main_mod.main() == 0
    assert not (tmp_path / "robo.lock").exists()
    assert main_mod.main() == 0                                # e roda de novo sem problema
