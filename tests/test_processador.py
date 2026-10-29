from openpyxl import load_workbook

from models.item import CONCLUIDO, DRY_RUN, ERRO, IGNORADO
from src.erros import AnexoFalhouError
from src.sap.simulado import SapSimulado
from src.servicos.processador import Processador
from tests.conftest import criar_pdf


def status_planilha(cfg):
    ws = load_workbook(cfg.planilha).active
    return {r[0].value: (r[2].value, r[4].value if ws.max_column >= 5 else None)
            for r in ws.iter_rows(min_row=2)}


def rodar(cfg, log, planilha, prov, sap, **kw):
    dry = kw.pop("dry_run", False)
    return Processador(cfg, planilha, prov, sap, log, dry_run=dry).executar(**kw)


def test_fluxo_feliz_anexa_e_atualiza_planilha(cfg, log, montar):
    criar_pdf(cfg.raiz_arquivos / "P-1", "a.pdf"); criar_pdf(cfg.raiz_arquivos / "P-1", "b.pdf")
    pl, prov = montar([("4500001001", "P-1", None)])
    sap = SapSimulado()
    r = rodar(cfg, log, pl, prov, sap)
    assert r.contagem() == {CONCLUIDO: 1} and not r.abortado
    assert sap.anexos["4500001001"] == ["a", "b"]
    assert status_planilha(cfg)["4500001001"][0] == "JÁ ANEXADO"


def test_idempotencia_segunda_execucao_nao_duplica(cfg, log, montar):
    criar_pdf(cfg.raiz_arquivos / "P-1", "a.pdf")
    pl, prov = montar([("4500001001", "P-1", None)])
    sap = SapSimulado()
    rodar(cfg, log, pl, prov, sap)
    # simula alguém zerando o status e rodando de novo: o SAP já tem o anexo
    ws_wb = load_workbook(cfg.planilha); ws_wb.active["C2"] = None; ws_wb.save(cfg.planilha)
    pl2, prov2 = montar([("4500001001", "P-1", None)])
    r = rodar(cfg, log, pl2, prov2, sap)
    assert sap.anexos["4500001001"] == ["a"]                       # continua 1 só
    assert [c for c in sap.chamadas if c[0] == "anexar"] == [("anexar", "4500001001", "a.pdf")]
    assert r.resultados[0].status == CONCLUIDO and r.resultados[0].ja_existiam == ["a.pdf"]


def test_envia_so_o_que_falta(cfg, log, montar):
    criar_pdf(cfg.raiz_arquivos / "P-1", "lote1.pdf"); criar_pdf(cfg.raiz_arquivos / "P-1", "lote2.pdf")
    pl, prov = montar([("4500001001", "P-1", None)])
    sap = SapSimulado(anexos_iniciais={"4500001001": ["LOTE1"]})  # caixa diferente de propósito
    r = rodar(cfg, log, pl, prov, sap)
    assert r.resultados[0].anexados == ["lote2.pdf"] and r.resultados[0].ja_existiam == ["lote1.pdf"]


def test_erro_em_um_item_nao_impede_os_outros(cfg, log, montar):
    for p in ("P-1", "P-2", "P-3"):
        criar_pdf(cfg.raiz_arquivos / p, "x.pdf")
    pl, prov = montar([("4500001001", "P-1", None), ("4500001002", "P-2", None),
                       ("4500001003", "P-3", None)])
    r = rodar(cfg, log, pl, prov, SapSimulado(inexistentes={"4500001002"}))
    assert [x.status for x in r.resultados] == [CONCLUIDO, ERRO, CONCLUIDO]
    assert "não existe" in r.resultados[1].mensagem
    assert not r.abortado


def test_pasta_ausente_nem_toca_no_sap(cfg, log, montar):
    pl, prov = montar([("4500001001", "SEM-PASTA", None)])
    cfg.raiz_arquivos.mkdir(parents=True, exist_ok=True)
    sap = SapSimulado()
    r = rodar(cfg, log, pl, prov, sap)
    assert r.resultados[0].status == ERRO and sap.chamadas == [("limpar",)]


def test_retentativa_recupera_falha_transitoria(cfg, log, montar, monkeypatch):
    monkeypatch.setattr("src.servicos.processador.time.sleep", lambda s: None)
    criar_pdf(cfg.raiz_arquivos / "P-1", "a.pdf")
    pl, prov = montar([("4500001001", "P-1", None)])

    class Instavel(SapSimulado):
        tentativas = 0
        def anexar(self, caminho):
            Instavel.tentativas += 1
            if Instavel.tentativas == 1:
                raise AnexoFalhouError("popup inesperado")
            super().anexar(caminho)
    r = rodar(cfg, log, pl, prov, Instavel())
    assert r.resultados[0].status == CONCLUIDO and Instavel.tentativas == 2


def test_falha_parcial_informa_o_que_entrou(cfg, log, montar, monkeypatch):
    monkeypatch.setattr("src.servicos.processador.time.sleep", lambda s: None)
    criar_pdf(cfg.raiz_arquivos / "P-1", "a.pdf"); criar_pdf(cfg.raiz_arquivos / "P-1", "b.pdf")
    pl, prov = montar([("4500001001", "P-1", None)])
    sap = SapSimulado(falha_anexo={"b.pdf"})
    r = rodar(cfg, log, pl, prov, sap)
    msg = r.resultados[0].mensagem
    assert r.resultados[0].status == ERRO and "já anexados: ['a.pdf']" in msg and "falhou: b.pdf" in msg
    # reexecução (após corrigir a causa) envia só o b
    sap.falha_anexo.clear()
    pl2, prov2 = montar([("4500001001", "P-1", "ERRO")])
    rodar(cfg, log, pl2, prov2, sap, reprocessar_erros=True)
    assert sap.anexos["4500001001"] == ["a", "b"]


def test_anexo_nao_confirmado_vira_erro(cfg, log, montar):
    criar_pdf(cfg.raiz_arquivos / "P-1", "a.pdf")
    pl, prov = montar([("4500001001", "P-1", None)])
    r = rodar(cfg, log, pl, prov, SapSimulado(nao_confirma={"4500001001"}))
    assert r.resultados[0].status == ERRO and "não consta" in r.resultados[0].mensagem


def test_queda_do_sap_aborta_e_preserva_pendentes(cfg, log, montar):
    for p in ("P-1", "P-2", "P-3"):
        criar_pdf(cfg.raiz_arquivos / p, "x.pdf")
    pl, prov = montar([("4500001001", "P-1", None), ("4500001002", "P-2", None),
                       ("4500001003", "P-3", None)])
    r = rodar(cfg, log, pl, prov, SapSimulado(cai_no_pedido="4500001002"))
    assert r.abortado and "perdida" in r.motivo_aborto
    st = status_planilha(cfg)
    assert st["4500001001"][0] == "JÁ ANEXADO"
    assert st["4500001002"][0] is None and st["4500001003"][0] is None  # seguem pendentes


def test_disjuntor_para_apos_falhas_tecnicas_seguidas(cfg, log, montar, monkeypatch):
    monkeypatch.setattr("src.servicos.processador.time.sleep", lambda s: None)
    pedidos = [(f"45000010{i:02d}", f"P-{i}", None) for i in range(1, 7)]
    for _, p, _ in pedidos:
        criar_pdf(cfg.raiz_arquivos / p, "x.pdf")
    pl, prov = montar(pedidos)
    # todo upload falha -> problema técnico sistêmico
    r = rodar(cfg, log, pl, prov, SapSimulado(falha_anexo={"x.pdf"}))
    assert r.abortado and "técnicas seguidas" in r.motivo_aborto
    assert len(r.resultados) == 3                      # parou no 3º, não processou os 6


def test_erros_de_dados_nao_acionam_o_disjuntor(cfg, log, montar):
    cfg.raiz_arquivos.mkdir(parents=True, exist_ok=True)
    pl, prov = montar([(f"45000010{i:02d}", f"SEM-{i}", None) for i in range(1, 8)])
    r = rodar(cfg, log, pl, prov, SapSimulado())
    assert not r.abortado and len(r.resultados) == 7   # 7 pastas ausentes, segue até o fim


def test_excecao_inesperada_vira_erro_do_item(cfg, log, montar):
    criar_pdf(cfg.raiz_arquivos / "P-1", "x.pdf"); criar_pdf(cfg.raiz_arquivos / "P-2", "x.pdf")
    pl, prov = montar([("4500001001", "P-1", None), ("4500001002", "P-2", None)])

    class Bugado(SapSimulado):
        def listar_anexos(self):
            if self.atual == "4500001001":
                raise KeyError("bug qualquer")
            return super().listar_anexos()
    r = rodar(cfg, log, pl, prov, Bugado())
    assert [x.status for x in r.resultados] == [ERRO, CONCLUIDO]
    assert "KeyError" in r.resultados[0].mensagem


def test_dry_run_nao_anexa_nem_altera_planilha(cfg, log, montar):
    criar_pdf(cfg.raiz_arquivos / "P-1", "a.pdf")
    pl, prov = montar([("4500001001", "P-1", None)])
    sap = SapSimulado()
    r = rodar(cfg, log, pl, prov, sap, dry_run=True)
    assert r.resultados[0].status == DRY_RUN and r.resultados[0].anexados == ["a.pdf"]
    assert not any(c[0] == "anexar" for c in sap.chamadas)
    assert status_planilha(cfg)["4500001001"][0] is None


def test_duplicata_ignorada_e_limite(cfg, log, montar):
    for p in ("P-1", "P-2", "P-3"):
        criar_pdf(cfg.raiz_arquivos / p, "x.pdf")
    pl, prov = montar([("4500001001", "P-1", None), ("4500001001", "P-1", None),
                       ("4500001002", "P-2", None), ("4500001003", "P-3", None)])
    r = rodar(cfg, log, pl, prov, SapSimulado(), limite=2)
    assert [x.status for x in r.resultados] == [CONCLUIDO, IGNORADO]


def test_planilha_aberta_no_excel_nao_perde_resultados(cfg, log, montar, monkeypatch):
    criar_pdf(cfg.raiz_arquivos / "P-1", "a.pdf")
    pl, prov = montar([("4500001001", "P-1", None)])
    monkeypatch.setattr("src.planilha.controle.time.sleep", lambda s: None)
    monkeypatch.setattr(pl, "salvar", lambda *a, **k: False)
    r = rodar(cfg, log, pl, prov, SapSimulado())
    assert r.resultados[0].status == CONCLUIDO         # resultado existe mesmo sem salvar
