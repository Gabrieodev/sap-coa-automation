"""Janelas do anexo na ME22N: 'Importar file' (SAP) e aviso 'Segurança do SAP GUI' -> 'Permitir'.

Tudo com adaptadores FALSOS: nenhum teste toca no SAP, no pywinauto ou no pywin32 reais, então
podem rodar em qualquer PC (inclusive com o SAP aberto) sem mexer em nada.
"""
import sys
import threading
import time
from pathlib import Path

import pytest

from src.erros import AnexoFalhouError
from src.sap.dialogo_arquivo import DialogoArquivo, JanelaInfo

SEG = JanelaInfo(202, "Segurança do SAP GUI", "#32770", ("Permitir", "Negar"))
OUTRA = JanelaInfo(303, "Calculadora", "ApplicationFrameWindow")
SELECIONAR_DOC = JanelaInfo(401, "Selecionar documento", "#32770")          # popup do "Outro pedido"
IMPORTAR_FILE = JanelaInfo(402, "Importar file", "#32770", ("&Abrir", "Cancelar", "Aj&uda"))


class PythoncomFalso:
    COINIT_APARTMENTTHREADED = 2

    def CoInitializeEx(self, modo):
        pass

    def CoUninitialize(self):
        pass


@pytest.fixture(autouse=True)
def _sem_com_real(monkeypatch):
    monkeypatch.setitem(sys.modules, "pythoncom", PythoncomFalso())


@pytest.fixture
def arquivo(tmp_path):
    p = tmp_path / "COA.pdf"
    p.write_bytes(b"%PDF-1.4 teste")
    return p


class SapFalso:
    """adaptador_sap: `tratar_importar_file` devolve o que for configurado."""

    def __init__(self, resposta=True):
        self.resposta, self.chamadas = resposta, 0

    def tratar_importar_file(self, caminho):
        self.chamadas += 1
        return self.resposta


class SapQueBloqueia:
    """Reproduz o comportamento real: confirmar o 'Importar file' (Press) só RETORNA depois que
    alguém clica em Permitir. Se ninguém clicar em 5 s, levanta (o robô travou)."""

    def __init__(self, liberado: threading.Event):
        self.liberado = liberado

    def tratar_importar_file(self, caminho):
        if not self.liberado.wait(timeout=5):
            raise TimeoutError("ninguém clicou em Permitir: o robô ficou travado esperando")
        return True


class WinFalso:
    """adaptador (pywinauto): janelas visíveis agora + cliques registrados."""

    def __init__(self, visiveis=(), clique_funciona=True, some_ao_clicar=True):
        self.visiveis = list(visiveis)
        self.clique_funciona, self.some_ao_clicar = clique_funciona, some_ao_clicar
        self.cliques, self.abertos = [], []
        self.clicado = threading.Event()
        self._lock = threading.Lock()

    def janelas(self):
        with self._lock:
            return list(self.visiveis)

    def preencher_e_abrir(self, handle, caminho):
        self.abertos.append((handle, Path(caminho).name))

    def clicar_botao(self, handle, botao_re):
        with self._lock:
            self.cliques.append(handle)
            if not self.clique_funciona:
                return False
            if self.some_ao_clicar:
                self.visiveis = [j for j in self.visiveis if j.handle != handle]
        self.clicado.set()
        return True


class LogFalso:
    def __init__(self):
        self.avisos = []

    def warning(self, msg, *args):
        self.avisos.append(msg % args if args else msg)


def montar(sap, win, **kw):
    return DialogoArquivo(timeout=kw.pop("timeout", 3), espera_seguranca=kw.pop("espera", 0.1),
                          adaptador=win, adaptador_sap=sap, intervalo=0.01, **kw)


def rodar(d, arquivo, espera=6):
    t = d.iniciar(arquivo)
    t.aguardar(espera)
    return t


# ------------------------------------------------------------------ fluxo normal
def test_importa_pelo_sap_e_clica_em_permitir(arquivo):
    win = WinFalso([SEG])
    t = rodar(montar(SapFalso(True), win), arquivo)
    assert t.concluida and t.seguranca_tratada and win.cliques == [202]


def test_aviso_que_aparece_um_pouco_depois_tambem_e_clicado(arquivo):
    win = WinFalso([])
    threading.Timer(0.3, lambda: win.visiveis.append(SEG)).start()
    t = rodar(montar(SapFalso(True), win, espera=1.5), arquivo)
    assert t.concluida and t.seguranca_tratada and win.cliques == [202]


def test_sem_aviso_conclui_depois_da_espera(arquivo):
    win = WinFalso([OUTRA])
    t = rodar(montar(SapFalso(True), win), arquivo)
    assert t.concluida and not t.seguranca_tratada and win.cliques == []


# ------------------------------------------------------------------ o defeito: precisa clicar a mão
def test_importar_que_bloqueia_ate_o_permitir_nao_trava_o_robo(arquivo):
    """O SAP só devolve o controle depois do clique em Permitir. O clique tem que vir de OUTRA thread."""
    win = WinFalso([SEG])
    sap = SapQueBloqueia(win.clicado)           # só é liberado quando o clique acontece
    t = rodar(montar(sap, win, timeout=4), arquivo)
    assert t.erro is None, t.erro
    assert t.concluida and t.seguranca_tratada and win.cliques == [202]


def test_nao_clica_duas_vezes_na_mesma_janela(arquivo):
    win = WinFalso([SEG], some_ao_clicar=False)     # a janela "continua" visível depois do clique
    t = rodar(montar(SapFalso(True), win), arquivo)
    assert t.concluida and win.cliques == [202]


def test_aviso_achado_pelo_botao_permitir_mesmo_com_titulo_desconhecido(arquivo):
    win = WinFalso([JanelaInfo(55, "Aviso", "#32770", ("Permitir", "Negar", "Ajuda"))])
    t = rodar(montar(SapFalso(True), win), arquivo)
    assert t.concluida and t.seguranca_tratada and win.cliques == [55]


def test_aviso_em_ingles_tambem_vale(arquivo):
    win = WinFalso([JanelaInfo(56, "SAP GUI Security", "#32770", ("Allow", "Deny"))])
    t = rodar(montar(SapFalso(True), win), arquivo)
    assert t.concluida and t.seguranca_tratada


def test_clique_que_nao_funciona_vira_erro_e_registra_as_janelas_no_log(arquivo):
    win, log = WinFalso([SEG], clique_funciona=False), LogFalso()
    t = montar(SapFalso(True), win, log=log).iniciar(arquivo)
    with pytest.raises(AnexoFalhouError, match="Permitir"):
        t.aguardar(6)
    assert any("clique em 'Permitir' falhou" in a and "Segurança do SAP GUI" in a for a in log.avisos)


def test_vigia_termina_sozinha_quando_o_anexo_acaba(arquivo):
    win = WinFalso([SEG])
    t = rodar(montar(SapFalso(True), win), arquivo)
    t.vigia.join(timeout=5)
    assert not t.vigia.is_alive()


def test_aguardar_com_sap_travado_estoura_o_prazo_e_para_a_vigia(arquivo):
    win = WinFalso([OUTRA])                      # nenhum aviso: ninguém libera o SAP
    liberado = threading.Event()
    t = montar(SapQueBloqueia(liberado), win, timeout=10).iniciar(arquivo)
    with pytest.raises(AnexoFalhouError, match="nao foram tratadas"):
        t.aguardar(0.5)
    t.vigia.join(timeout=3)
    assert not t.vigia.is_alive()
    liberado.set()                               # solta a thread principal (limpeza do teste)


# ------------------------------------------------------------------ janela de arquivo nativa (fallback)
def test_janela_nativa_importar_file_e_preenchida_quando_o_sap_nao_trata(arquivo):
    win = WinFalso([IMPORTAR_FILE])
    t = rodar(montar(SapFalso(False), win), arquivo)
    assert win.abertos == [(402, "COA.pdf")] and t.concluida


def test_selecionar_documento_nao_e_confundida_com_a_janela_de_arquivo(arquivo):
    win = WinFalso([SELECIONAR_DOC, IMPORTAR_FILE])
    rodar(montar(SapFalso(False), win), arquivo)
    assert [h for h, _ in win.abertos] == [402]


def test_arquivo_nunca_tratado_e_erro(arquivo):
    win = WinFalso([OUTRA])
    t = montar(SapFalso(False), win, timeout=0.5).iniciar(arquivo)
    with pytest.raises(AnexoFalhouError, match="janela de arquivo nao foi tratada"):
        t.aguardar(6)


def test_arquivo_inexistente_e_erro(tmp_path):
    t = montar(SapFalso(True), WinFalso()).iniciar(tmp_path / "nao_existe.pdf")
    with pytest.raises(AnexoFalhouError, match="nao encontrado"):
        t.aguardar(3)


def test_espera_pelo_aviso_encolhe_quando_ele_nao_aparece():
    d = DialogoArquivo(espera_seguranca=3.0, adaptador=WinFalso(), adaptador_sap=SapFalso())
    assert d._espera_atual() == 3.0              # ainda não sabemos
    d._seguranca_vista = False
    assert d._espera_atual() == 1.0              # não gasta 3 s em cada um dos 40 arquivos
    d._seguranca_vista = True
    assert d._espera_atual() == 3.0
