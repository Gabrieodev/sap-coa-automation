"""Comportamento para execução diária agendada: quem já está 'JÁ ANEXADO' não gasta tempo
(nem pasta, nem SAP), e sem pendências o robô nem conecta ao SAP."""
import sys

import pytest

import main as main_mod
from src.arquivos.provedor import PastaSincronizada
from src.sap.exceptions import SapNaoAbertoError, SapNaoLogadoError
from src.sap.preguicoso import SapPreguicoso
from src.sap.simulado import SapSimulado
from src.servicos.processador import Processador
from tests.conftest import criar_pdf
from tests.test_status_planilha import base, pl_, valores


class ProvedorEspiao(PastaSincronizada):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.consultados = []

    def obter_arquivos(self, processo):
        self.consultados.append(processo)
        return super().obter_arquivos(processo)


class FabricaEspia:
    """Fábrica de SAP que conta quantas vezes foi chamada (= quantas conexões ao SAP)."""
    def __init__(self, sap=None, erro=None):
        self.chamadas, self.sap, self.erro = 0, sap or SapSimulado(), erro

    def __call__(self):
        self.chamadas += 1
        if self.erro:
            raise self.erro
        return self.sap


def montar(cfg, log, linhas, fabrica):
    p = base(cfg.planilha, linhas)
    for proc, _, _ in linhas:
        if proc:
            criar_pdf(cfg.raiz_arquivos / proc, "x.pdf")
    prov = ProvedorEspiao(cfg.raiz_arquivos, cfg.extensoes_permitidas, log=log)
    sap = SapPreguicoso(fabrica, log)
    return Processador(cfg, pl_(p, log=log), prov, sap, log), prov, sap, p


def test_linhas_ja_anexadas_nao_abrem_pasta_nem_pedido(cfg, log):
    fab = FabricaEspia()
    proc, prov, sap, _ = montar(cfg, log, [
        ("P-1", "4500000001", "JÁ ANEXADO"), ("P-2", "4500000002", "ja anexado"),
        ("P-3", "4500000003", None),                       # a única pendente
        ("P-4", "4500000004", "JÁ ANEXADO")], fab)
    r = proc.executar()
    assert [x.item.pedido for x in r.resultados] == ["4500000003"]
    assert prov.consultados == ["P-3"]                      # nem a pasta das outras foi consultada
    assert [c for c in fab.sap.chamadas if c[0] == "abrir"] == [("abrir", "4500000003")]


def test_sem_pendencias_nao_conecta_ao_sap(cfg, log):
    fab = FabricaEspia()
    proc, prov, sap, p = montar(cfg, log, [("P-1", "4500000001", "JÁ ANEXADO"),
                                           ("P-2", "4500000002", "JÁ ANEXADO")], fab)
    antes = p.read_bytes()
    r = proc.executar()
    assert r.resultados == [] and not r.abortado
    assert fab.chamadas == 0 and not sap.conectado          # SAP nem foi tocado
    assert prov.consultados == []
    assert p.read_bytes() == antes                          # planilha não foi regravada


def test_conecta_uma_unica_vez_e_so_quando_precisa(cfg, log):
    fab = FabricaEspia()
    # P-1: sem pasta -> falha ANTES do SAP | P-2 e P-3: precisam do SAP
    proc, prov, sap, p = montar(cfg, log, [("P-1", "4500000001", None),
                                           ("P-2", "4500000002", None),
                                           ("P-3", "4500000003", None)], fab)
    import shutil
    shutil.rmtree(cfg.raiz_arquivos / "P-1")
    proc.executar()
    assert fab.chamadas == 1                                # uma conexão, reaproveitada
    assert [x[8] for x in valores(p)] == ["ERRO", "JÁ ANEXADO", "JÁ ANEXADO"]


def test_so_erros_antes_do_sap_nao_conectam(cfg, log):
    fab = FabricaEspia()
    proc, prov, sap, p = montar(cfg, log, [(None, "4500000001", None), ("P-2", "abc", None)], fab)
    r = proc.executar()
    assert [x.status for x in r.resultados] == ["ERRO", "ERRO"] and fab.chamadas == 0


@pytest.mark.parametrize("erro", [SapNaoAbertoError("SAP GUI não está aberto."),
                                  SapNaoLogadoError("nenhum ambiente logado")])
def test_sap_fechado_com_trabalho_pendente_aborta_sem_marcar_nada(cfg, log, erro):
    fab = FabricaEspia(erro=erro)
    proc, prov, sap, p = montar(cfg, log, [("P-1", "4500000001", None), ("P-2", "4500000002", None)], fab)
    r = proc.executar()
    assert r.abortado and r.resultados == []
    assert [x[8] for x in valores(p)] == [None, None]       # continuam em branco p/ a próxima execução


def test_limpar_popups_nunca_conecta():
    fab = FabricaEspia()
    sap = SapPreguicoso(fab)
    sap.limpar_popups()
    assert fab.chamadas == 0


# ------------------------------------------------------------------ main (sem tocar no SAP real)
@pytest.fixture
def ambiente_main(tmp_path, monkeypatch):
    monkeypatch.setattr(main_mod, "_conectar_sap_real", lambda cfg, log: (_ for _ in ()).throw(
        AssertionError("conectou ao SAP real durante o teste")))
    for k, v in {"COA_RAIZ_ARQUIVOS": tmp_path / "sp", "COA_LOGS_DIR": tmp_path / "logs",
                 "COA_PLANILHA": tmp_path / "base.xlsx"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.setattr(sys, "argv", ["main.py"])           # modo REAL (sem --simulado)
    return tmp_path


def test_main_diario_sem_novidades_termina_com_0_sem_sap(ambiente_main):
    base(ambiente_main / "base.xlsx", [("P-1", "4500000001", "JÁ ANEXADO"),
                                       ("P-2", "4500000002", "JÁ ANEXADO")])
    assert main_mod.main() == 0       # se tentasse conectar, o AssertionError do fixture falharia


def test_main_com_pendencia_e_sap_fechado_termina_com_2(ambiente_main, monkeypatch):
    base(ambiente_main / "base.xlsx", [("P-1", "4500000001", None)])
    criar_pdf(ambiente_main / "sp" / "P-1", "x.pdf")

    def sem_sap(cfg, log):
        raise SapNaoAbertoError("SAP GUI não está aberto.")
    monkeypatch.setattr(main_mod, "_conectar_sap_real", sem_sap)
    assert main_mod.main() == 2
    assert valores(ambiente_main / "base.xlsx")[0][8] is None   # segue em branco
