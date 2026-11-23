"""O robô preenche a cópia da base; o CSV é a memória. Cópia nova (sem status) -> status reposto."""
import datetime as dt
import hashlib
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

import main as main_mod
from src.planilha.estado import EstadoCsv
from tests.conftest import criar_pdf

CAB_BI = ["USUÁRIO RESPONSÁVEL", "STATUS GERAL", "MODAL", "CENTRO", "UNIDADE NOME", "UNIDADE UF",
          "PROCESSO", "PEDIDO SAP", "DATA CRIAÇÃO PEDIDO", "CÓDIGO MATERIAL"]
ROT = ["STATUS COA ROBÔ", "OBS COA ROBÔ", "DATA COA ROBÔ"]


def base_bi(caminho: Path, linhas):
    """Cópia da base do Power BI: G=PROCESSO, H=PEDIDO SAP, I=DATA CRIAÇÃO (não é status!)."""
    wb = Workbook(); ws = wb.active
    ws.append(CAB_BI)
    for proc, ped, material in linhas:
        ws.append(["Aron", "EM TRANSITO", "RODOVIARIA", 105, "MAUÁ", "SP", proc, ped,
                   dt.datetime(2026, 9, 23), material])
    wb.save(caminho)
    return caminho


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tabela(p):
    ws = load_workbook(p).active
    return [[c.value for c in r] for r in ws.iter_rows(min_row=1)]


@pytest.fixture
def amb(tmp_path, monkeypatch):
    for proc in ("0347-26", "0348-26", "0405-26"):
        criar_pdf(tmp_path / "sp" / proc, "coa.pdf")
    for k, v in {"COA_PLANILHA": tmp_path / "base.xlsx", "COA_RAIZ_ARQUIVOS": tmp_path / "sp",
                 "COA_LOGS_DIR": tmp_path / "logs", "COA_ARQUIVO_ESTADO": tmp_path / "estado.csv"}.items():
        monkeypatch.setenv(k, str(v))
    return tmp_path


def rodar(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado", *args])
    return main_mod.main()


def log_txt(amb):
    return "\n".join(f.read_text(encoding="utf-8") for f in sorted((amb / "logs").glob("execucao_*.log")))


def test_preenche_colunas_novas_no_fim_e_nao_mexe_nas_da_base(amb, monkeypatch):
    base_bi(amb / "base.xlsx", [("0347/26", 4501039840, 7000001593), ("0347/26", 4501039840, 7000001594),
                                ("0348/26", 4501039851, 7000001593)])
    assert rodar(monkeypatch) == 0
    t = tabela(amb / "base.xlsx")
    assert t[0][10:] == ROT                                         # K, L, M criadas no fim
    assert [r[10] for r in t[1:]] == ["JÁ ANEXADO"] * 3             # inclusive a linha repetida (outro material)
    assert t[1][8] == dt.datetime(2026, 9, 23) and t[1][:10] == tabela(amb / "base.xlsx")[1][:10]
    assert EstadoCsv(amb / "estado.csv").obter("4501039840", "0347/26")[0] == "CONCLUIDO"


def test_copia_nova_da_base_recebe_status_de_volta_sem_reabrir_o_sap(amb, monkeypatch):
    base_bi(amb / "base.xlsx", [("0347/26", 4501039840, 1), ("0348/26", 4501039851, 1)])
    rodar(monkeypatch)
    # novo envio do Power BI: sem as colunas do robô, outra ordem, uma linha nova
    base_bi(amb / "base.xlsx", [("0405/26", 4501061378, 1), ("0348/26", 4501039851, 1),
                                ("0347/26", 4501039840, 1)])
    assert rodar(monkeypatch) == 0
    t = tabela(amb / "base.xlsx")
    assert t[0][10:] == ROT
    assert {r[7]: r[10] for r in t[1:]} == {4501061378: "JÁ ANEXADO", 4501039851: "JÁ ANEXADO",
                                           4501039840: "JÁ ANEXADO"}
    assert "a processar: 1" in log_txt(amb)                      # só o pedido novo foi ao SAP
    assert t[3][12] and t[2][12]                                  # data do processamento reposta


def test_erro_tambem_e_reposto_e_nao_e_repetido(amb, monkeypatch):
    base_bi(amb / "base.xlsx", [("0999/26", 4501000001, 1)])          # sem pasta
    assert rodar(monkeypatch) == 1
    base_bi(amb / "base.xlsx", [("0999/26", 4501000001, 1), ("0348/26", 4501039851, 1)])
    assert rodar(monkeypatch) == 0                                    # erro antigo não conta de novo
    t = tabela(amb / "base.xlsx")
    assert t[1][10] == "ERRO" and "Nenhuma pasta" in t[1][11] and t[2][10] == "JÁ ANEXADO"


def test_dry_run_nao_escreve_nem_o_espelho(amb, monkeypatch):
    base_bi(amb / "base.xlsx", [("0347/26", 4501039840, 1)])
    rodar(monkeypatch)
    base_bi(amb / "base.xlsx", [("0347/26", 4501039840, 1), ("0348/26", 4501039851, 1)])
    antes = sha(amb / "base.xlsx")
    assert rodar(monkeypatch, "--dry-run") == 0
    assert sha(amb / "base.xlsx") == antes


def test_texto_manual_na_coluna_do_robo_e_respeitado(amb, monkeypatch):
    base_bi(amb / "base.xlsx", [("0347/26", 4501039840, 1)])
    rodar(monkeypatch)
    wb = load_workbook(amb / "base.xlsx"); wb.active["K2"] = "SEM COA"; wb.save(amb / "base.xlsx")
    assert rodar(monkeypatch) == 0
    assert tabela(amb / "base.xlsx")[1][10] == "SEM COA"


def test_forcar_refaz_so_o_pedido_indicado(amb, monkeypatch):
    base_bi(amb / "base.xlsx", [("0347/26", 4501039840, 1), ("0348/26", 4501039851, 1)])
    rodar(monkeypatch)
    assert "a processar: 2" in log_txt(amb)
    assert rodar(monkeypatch, "--forcar", "--pedidos", "4501039851") == 0
    assert "a processar: 1" in log_txt(amb)                # só o pedido indicado foi refeito
    # o arquivo de log não fica preso ao processo (no Windows, aberto = não apaga)
    for f in (amb / "logs").glob("execucao_*.log"):
        f.unlink()


def test_letra_de_coluna_inexistente_nao_e_inventada(amb, monkeypatch):
    base_bi(amb / "base.xlsx", [("0347/26", 4501039840, 1)])
    monkeypatch.setenv("COA_COL_STATUS", "Z")                        # letra: só vale se a coluna existir
    assert rodar(monkeypatch) == 2


def test_forcar_sem_limite_e_recusado(amb, monkeypatch):
    base_bi(amb / "base.xlsx", [("0347/26", 4501039840, 1)])
    assert rodar(monkeypatch, "--forcar") == 2
