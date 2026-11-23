"""Coluna de STATUS na própria planilha: em branco = anexar, 'JÁ ANEXADO' = concluído, etc.
Inclui as proteções por ser uma base compartilhada (linha mudou, edição manual, arquivo aberto,
backup, gravação atômica, Ctrl+C)."""
import sys

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.workbook.workbook import Workbook as WB

import main as main_mod
from models.item import CONCLUIDO, ERRO
from src.erros import PlanilhaError
from src.planilha.controle import PlanilhaControle, status_de_texto
from src.sap.simulado import SapSimulado
from src.servicos.processador import Processador
from tests.conftest import criar_pdf
from src.arquivos.provedor import PastaSincronizada

CAB = ["DATA", "FORNECEDOR", "PRODUTO", "NF", "INVOICE", "LOTE", "PROCESSO", "PEDIDO SAP",
       "STATUS", "OBS EQUIPE", "TOTAL"]


def base(caminho, linhas, cab=CAB):
    """A-F ruído | G PROCESSO | H PEDIDO SAP | I STATUS | J ruído | K fórmula (não pode ser tocada)."""
    wb = Workbook()
    ws = wb.active
    ws.append(cab)
    for i, (proc, ped, st) in enumerate(linhas, start=2):
        ws.append(["2026-01-01", "Forn", "Prod", "NF", "INV", "L1", proc, ped, st, "nota", f"=1+{i}"])
    wb.save(caminho)
    return caminho


def pl_(p, **kw):
    kw.setdefault("col_processo", "G"); kw.setdefault("col_pedido", "H"); kw.setdefault("col_status", "I")
    return PlanilhaControle(p, **kw)


def valores(p):
    return [[c.value for c in r] for r in load_workbook(p).active.iter_rows(min_row=2)]


# ------------------------------------------------------------------ vocabulário de status
@pytest.mark.parametrize("txt,cod", [
    (None, ""), ("", ""), ("  ", ""), ("JÁ ANEXADO", CONCLUIDO), ("já anexado", CONCLUIDO),
    ("Ja  Anexado", CONCLUIDO), ("ANEXADO", CONCLUIDO), ("concluído", CONCLUIDO),
    ("CONCLUIDO", CONCLUIDO), ("erro", ERRO), ("Pendente", "PENDENTE"),
    ("SEM COA", "SEM COA"),                        # desconhecido: volta normalizado
])
def test_status_de_texto(txt, cod):
    assert status_de_texto(txt) == cod


def test_quais_linhas_processar(tmp_path):
    p = base(tmp_path / "b.xlsx", [
        ("P-1", "4500000001", None), ("P-2", "4500000002", "PENDENTE"),
        ("P-3", "4500000003", "JÁ ANEXADO"), ("P-4", "4500000004", "ja anexado"),
        ("P-5", "4500000005", "ERRO"), ("P-6", "4500000006", "SEM COA")])
    it = pl_(p).carregar()
    assert [i.deve_processar() for i in it] == [True, True, False, False, False, False]
    assert [i.deve_processar(reprocessar_erros=True) for i in it] == [True, True, False, False, True, False]


def test_status_desconhecido_gera_aviso_e_nunca_e_sobrescrito(tmp_path, cfg, log, caplog):
    p = base(cfg.planilha, [("P-1", "4500000001", "SEM COA"), ("P-2", "4500000002", None)])
    for proc in ("P-1", "P-2"):
        criar_pdf(cfg.raiz_arquivos / proc, "x.pdf")
    prov = PastaSincronizada(cfg.raiz_arquivos, cfg.extensoes_permitidas, log=log)
    with caplog.at_level("WARNING", logger="teste"):
        Processador(cfg, pl_(p, log=log), prov, SapSimulado(), log).executar()
    assert "PULADAS" in caplog.text and "SEM COA" in caplog.text
    assert [r[8] for r in valores(p)] == ["SEM COA", "JÁ ANEXADO"]


# ------------------------------------------------------------------ gravação
def test_grava_status_e_nao_toca_nas_outras_colunas(tmp_path):
    p = base(tmp_path / "b.xlsx", [("P-1", "4500000001", None), ("P-2", 4500000002, None)])
    antes = valores(p)
    pl = pl_(p)
    a, b = pl.carregar()
    pl.atualizar(a, CONCLUIDO, "ok"); pl.atualizar(b, ERRO, "motivo")
    assert pl.salvar() is True
    depois = valores(p)
    assert [r[8] for r in depois] == ["JÁ ANEXADO", "ERRO"]
    for r_antes, r_depois in zip(antes, depois):           # todas as outras colunas idênticas,
        assert r_antes[:8] == r_depois[:8] and r_antes[9:] == r_depois[9:]
    assert depois[0][10] == "=1+2"                           # inclusive fórmulas


def test_colunas_opcionais_de_obs_e_data(tmp_path):
    cab = CAB[:9] + ["MOTIVO ROBÔ", "QUANDO"]
    p = base(tmp_path / "b.xlsx", [("P-1", "4500000001", None)], cab=cab)
    pl = pl_(p, col_obs="J", col_data="K")
    item = pl.carregar()[0]
    pl.atualizar(item, ERRO, "Nenhuma pasta para o processo 'P-1'"); pl.salvar()
    r = valores(p)[0]
    assert r[8] == "ERRO" and "Nenhuma pasta" in r[9] and r[10].startswith("20")


def test_coluna_de_status_sem_titulo_e_recusada(tmp_path):
    p = base(tmp_path / "b.xlsx", [("P-1", "4500000001", None)], cab=CAB[:8] + [None] + CAB[9:])
    with pytest.raises(PlanilhaError, match="não tem título"):
        pl_(p).carregar()


def test_modo_legado_continua_criando_colunas(tmp_path):
    from tests.conftest import criar_planilha
    p = criar_planilha(tmp_path / "c.xlsx", [("4500000001", "P-1", None)], cabecalho=("pedido", "processo"))
    pl = PlanilhaControle(p)
    item = pl.carregar()[0]
    pl.atualizar(item, CONCLUIDO, "ok"); pl.salvar()
    ws = load_workbook(p).active
    assert [c.value for c in ws[1]] == ["pedido", "processo", "status", "data_processamento", "observacao"]
    assert ws["C2"].value == "JÁ ANEXADO"


# ------------------------------------------------------------------ proteções (base compartilhada)
def test_linha_inserida_durante_a_execucao_nao_grava_na_linha_errada(tmp_path, log):
    p = base(tmp_path / "b.xlsx", [("P-1", "4500000001", None), ("P-2", "4500000002", None)])
    pl = pl_(p, log=log)
    a, b = pl.carregar()
    # outra pessoa insere uma linha no topo e salva enquanto o robô trabalhava
    wb = load_workbook(p); wb.active.insert_rows(2); wb.save(p)
    pl.atualizar(a, CONCLUIDO, "ok"); pl.atualizar(b, CONCLUIDO, "ok")
    pl.salvar()
    st = {r[7]: r[8] for r in valores(p) if r[7]}
    assert all(v is None for v in st.values()), "nenhuma linha pode ter sido marcada por engano"
    assert len(pl.conflitos) == 2 and "mudou na planilha" in pl.conflitos[0]


def test_status_digitado_a_mao_durante_a_execucao_nao_e_sobrescrito(tmp_path, log):
    p = base(tmp_path / "b.xlsx", [("P-1", "4500000001", None)])
    pl = pl_(p, log=log)
    item = pl.carregar()[0]
    wb = load_workbook(p); wb.active["I2"] = "NÃO ANEXAR"; wb.save(p)
    pl.atualizar(item, CONCLUIDO, "ok"); pl.salvar()
    assert valores(p)[0][8] == "NÃO ANEXAR" and "status manual" in pl.conflitos[0]


def test_arquivo_aberto_no_excel_mantem_pendente_e_salva_depois(tmp_path, monkeypatch):
    p = base(tmp_path / "b.xlsx", [("P-1", "4500000001", None)])
    pl = pl_(p)
    item = pl.carregar()[0]
    pl.atualizar(item, CONCLUIDO, "ok")
    monkeypatch.setattr("src.planilha.controle.time.sleep", lambda s: None)
    monkeypatch.setattr(WB, "save", lambda *a, **k: (_ for _ in ()).throw(PermissionError("em uso")))
    assert pl.salvar() is False and valores(p)[0][8] is None
    monkeypatch.undo()
    assert pl.salvar() is True and valores(p)[0][8] == "JÁ ANEXADO"


def test_nao_deixa_arquivo_temporario_nem_corrompe_se_a_gravacao_falha(tmp_path, monkeypatch):
    p = base(tmp_path / "b.xlsx", [("P-1", "4500000001", None)])
    original = p.read_bytes()
    pl = pl_(p)
    pl.atualizar(pl.carregar()[0], CONCLUIDO, "ok")

    def falha_no_meio(self, f):
        f.write(b"meio-arquivo"); raise OSError("disco cheio")
    monkeypatch.setattr(WB, "save", falha_no_meio)
    assert pl.salvar() is False
    assert p.read_bytes() == original                      # base intacta
    assert not list(tmp_path.glob("*.robo.tmp"))           # e sem lixo


def test_backup_feito_uma_vez_antes_da_primeira_gravacao(tmp_path):
    p = base(tmp_path / "b.xlsx", [("P-1", "4500000001", None), ("P-2", "4500000002", None)])
    original = p.read_bytes()
    pl = pl_(p, pasta_backup=tmp_path / "bk")
    a, b = pl.carregar()
    pl.atualizar(a, CONCLUIDO); pl.salvar(); pl.atualizar(b, CONCLUIDO); pl.salvar()
    backups = list((tmp_path / "bk").glob("b_*.xlsx"))
    assert len(backups) == 1 and backups[0].read_bytes() == original   # cópia do estado ORIGINAL


def test_aba_renomeada_durante_a_execucao_nao_derruba(tmp_path, log):
    p = base(tmp_path / "b.xlsx", [("P-1", "4500000001", None)])
    pl = pl_(p, log=log)
    item = pl.carregar()[0]
    wb = load_workbook(p); wb.active.title = "Outro nome"; wb.save(p)
    pl.atualizar(item, CONCLUIDO); assert pl.salvar() is False   # sem exceção; segue pendente


# ------------------------------------------------------------------ processador
def _proc(cfg, log, linhas, sap=None, **kw):
    p = base(cfg.planilha, linhas)
    for proc, _, _ in linhas:
        criar_pdf(cfg.raiz_arquivos / proc, "x.pdf")
    pl = pl_(p, log=log, **kw)
    prov = PastaSincronizada(cfg.raiz_arquivos, cfg.extensoes_permitidas, log=log)
    return Processador(cfg, pl, prov, sap or SapSimulado(), log), pl, p


def test_salva_a_cada_n_e_no_fim(cfg, log):
    cfg.salvar_a_cada = 2
    proc, pl, _ = _proc(cfg, log, [(f"P-{i}", f"450000000{i}", None) for i in range(1, 6)])
    chamadas = []
    original = pl.salvar
    pl.salvar = lambda *a, **k: (chamadas.append(1), original(*a, **k))[1]
    proc.executar()
    assert len(chamadas) == 3                      # após o 2º, após o 4º, e o final (finally)


def test_ctrl_c_encerra_limpo_e_salva_o_que_ja_foi_feito(cfg, log):
    cfg.salvar_a_cada = 99                         # nada seria salvo antes do fim...
    class Interrompe(SapSimulado):
        def abrir_pedido(self, numero):
            if numero == "4500000002":
                raise KeyboardInterrupt
            super().abrir_pedido(numero)
    proc, pl, p = _proc(cfg, log, [("P-1", "4500000001", None), ("P-2", "4500000002", None),
                                   ("P-3", "4500000003", None)], sap=Interrompe())
    r = proc.executar()                            # não propaga a exceção: devolve o resumo
    assert r.abortado and "Ctrl+C" in r.motivo_aborto
    assert [x.item.pedido for x in r.resultados] == ["4500000001"]
    assert [x[8] for x in valores(p)] == ["JÁ ANEXADO", None, None]   # ...mas o finally salvou o 1º


def test_segunda_execucao_nao_refaz_o_que_ja_esta_anexado(cfg, log):
    proc, pl, p = _proc(cfg, log, [("P-1", "4500000001", None), ("P-2", "4500000002", None)])
    proc.executar()
    sap2 = SapSimulado()
    prov = PastaSincronizada(cfg.raiz_arquivos, cfg.extensoes_permitidas, log=log)
    r = Processador(cfg, pl_(p, log=log), prov, sap2, log).executar()
    assert r.resultados == [] and sap2.chamadas == []


# ------------------------------------------------------------------ main ponta a ponta (modo coluna na planilha)
# Coluna de status por LETRA (I): estes testes usam o layout antigo de 10 colunas.
def test_main_grava_status_na_coluna_I_e_respeita_o_que_e_texto_manual(tmp_path, monkeypatch):
    p = base(tmp_path / "base.xlsx", [("PROC-A", "4500002001", None), ("PROC-B", "4500002002", "SEM COA"),
                                      ("PROC-C", "4500002003", "JÁ ANEXADO"), ("PROC-D", "4500002004", None)])
    for proc in ("PROC-A", "PROC-B", "PROC-C"):
        criar_pdf(tmp_path / "sp" / proc, "coa.pdf")       # PROC-D: sem pasta -> ERRO
    for k, v in {"COA_PLANILHA": p, "COA_RAIZ_ARQUIVOS": tmp_path / "sp", "COA_LOGS_DIR": tmp_path / "logs",
                 "COA_COL_OBS": "J", "COA_COL_STATUS": "I", "COA_COL_DATA": "",
                 "COA_ARQUIVO_ESTADO": tmp_path / "estado.csv"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado"])
    assert main_mod.main() == 1                              # 1 = houve item com erro
    r = valores(p)
    assert [x[8] for x in r] == ["JÁ ANEXADO", "SEM COA", "JÁ ANEXADO", "ERRO"]
    assert "Nenhuma pasta" in r[3][9]                       # motivo do erro na coluna J
    assert r[1][9] == "nota"                                 # linha pulada: coluna J intocada
    assert list((tmp_path / "logs" / "backup_planilha").glob("base_*.xlsx"))
    assert (tmp_path / "estado.csv").exists()                # memória do robô gravada junto
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado", "--dry-run"])
    assert main_mod.main() == 0                              # nada novo a processar


def test_main_sem_titulo_na_coluna_de_status_sai_com_2(tmp_path, monkeypatch):
    p = base(tmp_path / "base.xlsx", [("PROC-A", "4500002001", None)], cab=CAB[:8] + [None] + CAB[9:])
    for k, v in {"COA_PLANILHA": p, "COA_RAIZ_ARQUIVOS": tmp_path / "sp", "COA_LOGS_DIR": tmp_path / "logs",
                 "COA_COL_STATUS": "I", "COA_ARQUIVO_ESTADO": tmp_path / "estado.csv"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado"])
    assert main_mod.main() == 2


# ------------------------------------------------------------------ guarda da coluna de status
def test_coluna_de_status_com_datas_e_recusada_com_mensagem_clara(tmp_path):
    """Caso real: a coluna I da base é 'DATA CRIAÇÃO PEDIDO'."""
    import datetime as dt
    linhas = [(f"0{i}/26", f"45000000{i:02d}", dt.datetime(2026, 1, i)) for i in range(1, 9)]
    cab = CAB[:8] + ["DATA CRIAÇÃO PEDIDO"] + CAB[9:]
    p = base(tmp_path / "b.xlsx", linhas, cab=cab)
    with pytest.raises(PlanilhaError, match=r"coluna I .*DATA CRIAÇÃO PEDIDO.*COA_COL_STATUS"):
        pl_(p).carregar()


def test_poucos_textos_manuais_nao_disparam_a_guarda(tmp_path):
    linhas = [(f"P-{i}", f"45000000{i:02d}", "SEM COA" if i < 3 else None) for i in range(1, 9)]
    it = pl_(base(tmp_path / "b.xlsx", linhas)).carregar()          # 2 de 8: ok
    assert len(it) == 8
