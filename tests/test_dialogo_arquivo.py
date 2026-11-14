"""Janelas do anexo na ME22N: 'Abrir' + 'Segurança do SAP GUI' -> 'Permitir' (sem Windows, com fake)."""
from pathlib import Path

import pytest

from src.erros import AnexoFalhouError
from src.sap.dialogo_arquivo import DialogoArquivo, JanelaInfo

ABRIR = JanelaInfo(101, "Abrir", "#32770")
SEG = JanelaInfo(202, "Segurança do SAP GUI", "#32770")
OUTRA = JanelaInfo(303, "Calculadora", "ApplicationFrameWindow")


class AdaptadorFalso:
    """`roteiro`: o que janelas() devolve a cada chamada (a última se repete)."""
    def __init__(self, roteiro, clique_seguranca=True):
        self.roteiro, self.n, self.clique_seguranca = roteiro, 0, clique_seguranca
        self.eventos = []

    def janelas(self):
        i = min(self.n, len(self.roteiro) - 1); self.n += 1
        return self.roteiro[i]

    def preencher_e_abrir(self, handle, caminho):
        self.eventos.append(("abrir", handle, Path(caminho).name))

    def clicar_botao(self, handle, botao_re):
        self.eventos.append(("clique", handle, botao_re))
        return self.clique_seguranca


def rodar(ad, **kw):
    d = DialogoArquivo(timeout=2, espera_seguranca=0.05, adaptador=ad, intervalo=0, **kw)
    t = d.iniciar(Path("coa.pdf")); t.aguardar(5)
    return d, t


def test_abrir_depois_permitir():
    ad = AdaptadorFalso([[OUTRA], [OUTRA, ABRIR], [OUTRA, SEG]])
    d, t = rodar(ad)
    assert [e[:2] for e in ad.eventos] == [("abrir", 101), ("clique", 202)]
    assert t.concluida and t.seguranca_tratada
    assert "permitir" in ad.eventos[1][2].lower()


def test_permitir_antes_de_abrir():
    ad = AdaptadorFalso([[SEG], [ABRIR]])
    d, t = rodar(ad)
    assert [e[:2] for e in ad.eventos] == [("clique", 202), ("abrir", 101)]
    assert t.concluida and t.seguranca_tratada


def test_sem_aviso_de_seguranca_conclui_depois_da_espera():
    ad = AdaptadorFalso([[ABRIR], [OUTRA]])
    d, t = rodar(ad)
    assert t.concluida and not t.seguranca_tratada
    assert [e[0] for e in ad.eventos] == ["abrir"]


def test_janela_abrir_que_nao_aparece_e_erro():
    d = DialogoArquivo(timeout=0.3, adaptador=AdaptadorFalso([[OUTRA]]), intervalo=0.01)
    t = d.iniciar(Path("coa.pdf"))
    with pytest.raises(AnexoFalhouError, match="Abrir"):
        t.aguardar(5)


def test_aviso_de_seguranca_sem_conseguir_clicar_e_erro():
    ad = AdaptadorFalso([[ABRIR, SEG]], clique_seguranca=False)
    d = DialogoArquivo(timeout=0.3, espera_seguranca=0.05, adaptador=ad, intervalo=0.01)
    t = d.iniciar(Path("coa.pdf"))
    with pytest.raises(AnexoFalhouError, match="Permitir"):
        t.aguardar(5)


def test_calculadora_e_outras_janelas_sao_ignoradas():
    ad = AdaptadorFalso([[OUTRA, JanelaInfo(9, "Abrir com...", "ApplicationFrameWindow"), ABRIR]])
    d, t = rodar(ad)
    assert [e[:2] for e in ad.eventos] == [("abrir", 101)]       # só a #32770 'Abrir'


def test_espera_pelo_aviso_encolhe_quando_ele_nao_aparece():
    ad = AdaptadorFalso([[ABRIR]])
    d = DialogoArquivo(timeout=2, espera_seguranca=3.0, adaptador=ad, intervalo=0)
    assert d._espera_atual() == 3.0                    # ainda não sabemos
    d._seguranca_vista = False                         # no anexo anterior não apareceu
    assert d._espera_atual() == 1.0                    # não gasta 3 s em cada um dos 40 arquivos
    d._seguranca_vista = True
    assert d._espera_atual() == 3.0


def test_titulos_em_ingles_tambem_valem():
    ad = AdaptadorFalso([[JanelaInfo(1, "Open", "#32770"), JanelaInfo(2, "SAP GUI Security", "#32770")]])
    d, t = rodar(ad)
    assert t.concluida and t.seguranca_tratada
