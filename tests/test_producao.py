"""Cobre o que mudou para produção: colunas G/H, planilha só-leitura + estado em CSV,
busca em subpastas, filtros de linhas/pedidos, configuração por ambiente e o main ponta a ponta."""
import hashlib
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

import config as cfg_mod
import main as main_mod
from src.arquivos.provedor import PastaSincronizada
from src.erros import PastaProcessoAmbiguaError, PastaProcessoNaoEncontradaError, PlanilhaError
from src.planilha.controle import PlanilhaControle
from src.planilha.estado import EstadoCsv
from src.sap.simulado import SapSimulado
from src.servicos.processador import Processador
from tests.conftest import criar_pdf


def planilha_gh(caminho: Path, linhas, linha_cab=1):
    """Layout de produção: A-F ruído, G=PROCESSO, H=PEDIDO SAP, I ruído."""
    wb = Workbook()
    ws = wb.active
    for _ in range(linha_cab - 1):
        ws.append(["Relatório COA", "gerado manualmente"])
    ws.append(["DATA", "FORNECEDOR", "PRODUTO", "NF", "INVOICE", "LOTE", "PROCESSO", "PEDIDO SAP", "OBS"])
    for proc, ped in linhas:
        ws.append(["2026-01-01", "Forn", "Prod", "NF1", "INV1", "L1", proc, ped, "x"])
    wb.save(caminho)
    return caminho


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ------------------------------------------------------------------ colunas G / H
def test_le_colunas_G_e_H_ignorando_as_demais(tmp_path):
    p = planilha_gh(tmp_path / "b.xlsx", [("PROC-1", "4500001001"), ("PROC-2", 4500001002)])
    it = PlanilhaControle(p, col_processo="G", col_pedido="H", gravar_na_planilha=False,
                          arquivo_estado=tmp_path / "e.csv").carregar()
    assert [(i.processo, i.pedido) for i in it] == [("PROC-1", "4500001001"), ("PROC-2", "4500001002")]


def test_coluna_por_nome_do_cabecalho_e_linha_de_cabecalho_deslocada(tmp_path):
    p = planilha_gh(tmp_path / "b.xlsx", [("PROC-1", "4500001001")], linha_cab=3)
    it = PlanilhaControle(p, col_processo="PROCESSO", col_pedido="PEDIDO SAP", linha_cabecalho=3,
                          gravar_na_planilha=False, arquivo_estado=tmp_path / "e.csv").carregar()
    assert it[0].linha == 4 and it[0].pedido == "4500001001"


def test_coluna_inexistente_gera_erro_claro(tmp_path):
    p = planilha_gh(tmp_path / "b.xlsx", [("PROC-1", "4500001001")])
    with pytest.raises(PlanilhaError, match="'PEDIDO COMPRA' não encontrada"):
        PlanilhaControle(p, col_pedido="PEDIDO COMPRA", col_processo="G", gravar_na_planilha=False,
                         arquivo_estado=tmp_path / "e.csv").carregar()


def test_coluna_errada_por_letra_aparece_no_log(tmp_path, log, caplog):
    """Se a coluna G/H não for o que se espera, o cabeçalho lido aparece no log para conferência."""
    p = planilha_gh(tmp_path / "b.xlsx", [("PROC-1", "4500001001")])
    with caplog.at_level("INFO", logger="teste"):
        PlanilhaControle(p, log=log, col_processo="F", col_pedido="H", gravar_na_planilha=False,
                         arquivo_estado=tmp_path / "e.csv").carregar()
    assert "'LOTE'" in caplog.text and "'PEDIDO SAP'" in caplog.text


# ------------------------------------------------------------------ planilha só leitura + estado
def test_modo_leitura_nunca_altera_a_planilha(tmp_path):
    p = planilha_gh(tmp_path / "b.xlsx", [("PROC-1", "4500001001")])
    antes = sha(p)
    pl = PlanilhaControle(p, col_processo="G", col_pedido="H", gravar_na_planilha=False,
                          arquivo_estado=tmp_path / "e.csv")
    item = pl.carregar()[0]
    pl.atualizar(item, "CONCLUIDO", "ok")
    assert pl.salvar() is True
    assert sha(p) == antes                                   # byte a byte igual
    assert (tmp_path / "e.csv").exists()


def test_estado_persiste_entre_execucoes(tmp_path):
    p = planilha_gh(tmp_path / "b.xlsx", [("PROC-1", "4500001001"), ("PROC-2", "4500001002")])
    kw = dict(col_processo="G", col_pedido="H", gravar_na_planilha=False, arquivo_estado=tmp_path / "e.csv")
    pl = PlanilhaControle(p, **kw)
    a, b = pl.carregar()
    pl.atualizar(a, "CONCLUIDO", "ok"); pl.atualizar(b, "ERRO", "falhou"); pl.salvar()
    novo = PlanilhaControle(p, **kw).carregar()
    assert [i.status for i in novo] == ["CONCLUIDO", "ERRO"]
    assert [i.deve_processar() for i in novo] == [False, False]
    assert [i.deve_processar(reprocessar_erros=True) for i in novo] == [False, True]


def test_duplicata_nao_sobrescreve_o_estado_da_original(tmp_path):
    p = planilha_gh(tmp_path / "b.xlsx", [("PROC-1", "4500001001"), ("PROC-1", "4500001001")])
    pl = PlanilhaControle(p, col_processo="G", col_pedido="H", gravar_na_planilha=False,
                          arquivo_estado=tmp_path / "e.csv")
    original, dup = pl.carregar()
    pl.atualizar(original, "CONCLUIDO", "ok"); pl.atualizar(dup, "IGNORADO", "duplicata")
    pl.salvar()
    assert EstadoCsv(tmp_path / "e.csv").obter("4500001001", "PROC-1")[0] == "CONCLUIDO"


def test_modo_leitura_exige_arquivo_de_estado(tmp_path):
    with pytest.raises(ValueError, match="arquivo_estado"):
        PlanilhaControle(tmp_path / "b.xlsx", gravar_na_planilha=False)


def test_estado_travado_nao_derruba_e_salva_depois(tmp_path, monkeypatch):
    e = EstadoCsv(tmp_path / "e.csv")
    e.registrar("1", "P", "CONCLUIDO")
    real = __import__("os").replace
    monkeypatch.setattr("src.planilha.estado.os.replace",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError("em uso")))
    assert e.salvar() is False
    monkeypatch.setattr("src.planilha.estado.os.replace", real)
    assert e.salvar() is True and EstadoCsv(tmp_path / "e.csv").obter("1", "P")[0] == "CONCLUIDO"


# ------------------------------------------------------------------ subpastas
def test_busca_em_subpastas_por_profundidade(tmp_path):
    criar_pdf(tmp_path / "sp" / "2026" / "PROC-9", "a.pdf")
    assert PastaSincronizada(tmp_path / "sp", profundidade=2).obter_arquivos("PROC-9")[0].name == "a.pdf"
    with pytest.raises(PastaProcessoNaoEncontradaError):            # profundidade 1 não enxerga
        PastaSincronizada(tmp_path / "sp", profundidade=1).obter_arquivos("PROC-9")


def test_mesmo_processo_em_dois_anos_e_ambiguo(tmp_path):
    criar_pdf(tmp_path / "sp" / "2025" / "PROC-9", "a.pdf")
    criar_pdf(tmp_path / "sp" / "2026" / "PROC-9", "b.pdf")
    with pytest.raises(PastaProcessoAmbiguaError, match="2025"):
        PastaSincronizada(tmp_path / "sp", profundidade=2).obter_arquivos("PROC-9")


# ------------------------------------------------------------------ filtros
def _proc(cfg, log, tmp_path, linhas):
    p = planilha_gh(cfg.planilha, linhas)
    for proc, _ in linhas:
        criar_pdf(cfg.raiz_arquivos / proc, "x.pdf")
    pl = PlanilhaControle(p, log=log, col_processo="G", col_pedido="H", gravar_na_planilha=False,
                          arquivo_estado=tmp_path / "e.csv")
    prov = PastaSincronizada(cfg.raiz_arquivos, cfg.extensoes_permitidas, log=log)
    return Processador(cfg, pl, prov, SapSimulado(), log)


LINHAS5 = [(f"P-{i}", f"45000010{i:02d}") for i in range(1, 6)]   # linhas 2..6


def test_filtro_de_linhas(cfg, log, tmp_path):
    r = _proc(cfg, log, tmp_path, LINHAS5).executar(linhas=(3, 4))
    assert [x.item.linha for x in r.resultados] == [3, 4]


def test_filtro_linha_inicial_aberta(cfg, log, tmp_path):
    r = _proc(cfg, log, tmp_path, LINHAS5).executar(linhas=(5, None))
    assert [x.item.linha for x in r.resultados] == [5, 6]


def test_filtro_de_pedidos(cfg, log, tmp_path):
    r = _proc(cfg, log, tmp_path, LINHAS5).executar(pedidos={"4500001002", "4500001005"})
    assert [x.item.pedido for x in r.resultados] == ["4500001002", "4500001005"]


@pytest.mark.parametrize("txt,esperado", [("2-50", (2, 50)), ("100-", (100, None)),
                                          ("-50", (None, 50)), ("7", (7, 7))])
def test_parse_intervalo(txt, esperado):
    assert main_mod._intervalo(txt) == esperado


def test_parse_intervalo_invalido():
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        main_mod._intervalo("abc")


# ------------------------------------------------------------------ configuração
def test_defaults_de_producao():
    c = cfg_mod.Config()
    assert (c.col_processo, c.col_pedido) == ("PROCESSO", "PEDIDO SAP")   # por nome, não por posição
    # o robô preenche a cópia da base (colunas criadas pelo NOME no fim da tabela); CSV é a memória
    assert c.gravar_status_na_planilha is True and c.col_status == "STATUS COA ROBÔ"
    assert c.extensoes_permitidas == () and c.col_filtro is None
    assert c.col_obs == "OBS COA ROBÔ" and c.col_data == "DATA COA ROBÔ"
    assert "ICLBRComexTeam" in c.url_base_controle and c.planilha is None and c.raiz_arquivos is None


def test_variaveis_de_ambiente_sobrescrevem(monkeypatch, tmp_path):
    monkeypatch.setenv("COA_COL_PEDIDO", "K")
    monkeypatch.setenv("COA_GRAVAR_STATUS_NA_PLANILHA", "nao")
    monkeypatch.setenv("COA_COL_STATUS", "K")
    monkeypatch.setenv("COA_COL_OBS", "L")
    monkeypatch.setenv("COA_PROFUNDIDADE_BUSCA", "3")
    monkeypatch.setenv("COA_EXTENSOES_PERMITIDAS", ".PDF, .xlsx")
    monkeypatch.setenv("COA_RAIZ_ARQUIVOS", str(tmp_path))
    monkeypatch.setenv("COA_ABA", "Base de dados coa")
    c = cfg_mod.carregar()
    assert c.col_pedido == "K" and c.gravar_status_na_planilha is False
    assert c.col_status == "K" and c.col_obs == "L"
    assert c.profundidade_busca == 3 and c.extensoes_permitidas == (".pdf", ".xlsx")
    assert c.raiz_arquivos == tmp_path and c.aba == "Base de dados coa"


# ------------------------------------------------------------------ main ponta a ponta
@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    plan = planilha_gh(tmp_path / "base.xlsx", [("PROC-A", "4500002001"), ("PROC-B", "4500002002")])
    for proc in ("PROC-A", "PROC-B"):
        criar_pdf(tmp_path / "sp" / proc, "coa.pdf")
    monkeypatch.setenv("COA_GRAVAR_STATUS_NA_PLANILHA", "nao")   # estes testes cobrem o modo só-leitura
    for k, v in {"COA_PLANILHA": plan, "COA_RAIZ_ARQUIVOS": tmp_path / "sp",
                 "COA_ARQUIVO_ESTADO": tmp_path / "estado.csv", "COA_LOGS_DIR": tmp_path / "logs"}.items():
        monkeypatch.setenv(k, str(v))
    return tmp_path


def rodar_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["main.py", *args])
    return main_mod.main()


def test_main_simulado_ponta_a_ponta(ambiente, monkeypatch):
    plan = ambiente / "base.xlsx"; antes = sha(plan)
    assert rodar_main(monkeypatch, "--simulado") == 0
    assert sha(plan) == antes                                          # planilha intacta
    est = EstadoCsv(ambiente / "estado.csv")
    assert est.obter("4500002001", "PROC-A")[0] == "CONCLUIDO"
    assert list((ambiente / "logs").glob("relatorio_*.csv")) and list((ambiente / "logs").glob("execucao_*.log"))
    assert rodar_main(monkeypatch, "--simulado") == 0                  # 2ª vez: nada a fazer


def test_main_dry_run_nao_cria_estado(ambiente, monkeypatch):
    assert rodar_main(monkeypatch, "--simulado", "--dry-run") == 0
    assert not (ambiente / "estado.csv").exists()


def test_main_filtra_por_pedido(ambiente, monkeypatch):
    rodar_main(monkeypatch, "--simulado", "--pedidos", "4500002002")
    est = EstadoCsv(ambiente / "estado.csv")
    assert est.obter("4500002001", "PROC-A") is None and est.obter("4500002002", "PROC-B")


def test_main_planilha_inexistente_sai_com_2(ambiente, monkeypatch):
    monkeypatch.setenv("COA_PLANILHA", str(ambiente / "nao_existe.xlsx"))
    assert rodar_main(monkeypatch, "--simulado") == 2
