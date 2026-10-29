import logging
from pathlib import Path

import pytest
from openpyxl import Workbook

from config import Config
from src.arquivos.provedor import PastaSincronizada
from src.planilha.controle import PlanilhaControle


def criar_pdf(pasta: Path, nome: str, conteudo=b"%PDF-1.4 teste"):
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_bytes(conteudo)


def criar_planilha(caminho: Path, linhas, cabecalho=("pedido_sap", "processo", "status")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(cabecalho))
    for l in linhas:
        ws.append(list(l))
    wb.save(caminho)
    return caminho


@pytest.fixture
def log():
    l = logging.getLogger("teste")
    l.setLevel(logging.DEBUG)
    return l


@pytest.fixture
def cfg(tmp_path):
    return Config(planilha=tmp_path / "c.xlsx", raiz_arquivos=tmp_path / "sp",
                  logs_dir=tmp_path / "logs", tentativas_anexo=2,
                  max_erros_inesperados_seguidos=3)


@pytest.fixture
def montar(tmp_path, cfg, log):
    """Devolve função que monta planilha+provedor a partir das linhas."""
    def _montar(linhas, **kw):
        criar_planilha(cfg.planilha, linhas)
        return (PlanilhaControle(cfg.planilha, log=log),
                PastaSincronizada(cfg.raiz_arquivos, cfg.extensoes_permitidas, log=log))
    return _montar
