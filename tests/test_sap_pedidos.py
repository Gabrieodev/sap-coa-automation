"""Testa SapPedidos (a classe que fala com o SAP) contra uma sessão COM falsa."""
from pathlib import Path

import pytest

from src.erros import AnexoFalhouError
from src.sap import seletores as sel
from src.sap.dialogo_arquivo import DialogoArquivo, TarefaDialogo
from src.sap.exceptions import (ElementoSapNaoEncontradoError, PedidoBloqueadoError,
                                PedidoComErroError, PedidoNaoEncontradoError,
                                SemAutorizacaoError, SessaoSapPerdidaError)
from src.sap.navegacao import SapNavigation
from src.sap.pedidos import SapPedidos


class com_error(Exception):  # o nome da classe é o que o código procura
    pass


class El:
    def __init__(self, sessao, id_):
        self.s, self.id = sessao, id_
        self.text = ""
        self.MessageType, self.Text = "", ""

    # botões / janelas
    def press(self):
        self.s.eventos.append(("press", self.id))
        if self.id == sel.BTN_OUTRO_PEDIDO:
            self.s.dialogo_pedido = True
            self.s.popups = 1

    def sendVKey(self, k):
        self.s.eventos.append(("vkey", self.id, k))
        if self.id == "wnd[1]" and self.s.dialogo_pedido:
            campo = self.s.el(sel.CAMPO_PEDIDO_DIALOGO).text
            msg = self.s.mensagens.get(campo)
            sb = self.s.el("wnd[0]/sbar")
            if msg:
                sb.MessageType, sb.Text = "E", msg      # diálogo permanece aberto, como no SAP
            else:
                sb.MessageType, sb.Text = "S", ""
                self.s.dialogo_pedido, self.s.popups = False, 0

    def close(self):
        self.s.eventos.append(("close", self.id))
        self.s.dialogo_pedido, self.s.popups = False, 0

    # GOS
    def pressContextButton(self, b):
        self.s.eventos.append(("ctx_button", b))

    def selectContextMenuItem(self, item):
        self.s.eventos.append(("ctx_item", item))
        if item == sel.GOS_LISTA_ANEXOS and self.s.tem_grid:
            self.s.popups = 1
        if item == sel.GOS_CRIAR_ANEXO and self.s.erro_ao_criar:
            sb = self.s.el("wnd[0]/sbar"); sb.MessageType, sb.Text = "E", self.s.erro_ao_criar

    # grid
    @property
    def RowCount(self): return len(self.s.anexos)
    @property
    def ColumnOrder(self): return ["BITM_DESCR"]
    def GetCellValue(self, i, col): return self.s.anexos[i]


class SessaoFalsa:
    def __init__(self):
        self.eventos, self.mensagens, self.anexos = [], {}, []
        self.tem_grid, self.erro_ao_criar = True, None
        self.dialogo_pedido, self.popups = False, 0
        self.transacao, self._els, self.morta = "SESSION_MANAGER", {}, False
        self.Busy = False

    class _Info:
        def __init__(self, s): self.s = s
        @property
        def Transaction(self): return self.s.transacao
        @property
        def SystemName(self):
            if self.s.morta: raise com_error("RPC server unavailable")
            return "DEV"

    @property
    def Info(self): return self._Info(self)

    class _Children:
        def __init__(self, s): self.s = s
        @property
        def Count(self): return 1 + self.s.popups

    @property
    def Children(self): return self._Children(self)

    def StartTransaction(self, cod):
        self.eventos.append(("start", cod)); self.transacao = cod

    def el(self, id_):
        return self._els.setdefault(id_, El(self, id_))

    def findById(self, id_):
        if self.morta:
            raise com_error("RPC server unavailable")
        if id_ == sel.CAMPO_PEDIDO_DIALOGO and not self.dialogo_pedido:
            raise com_error("The control could not be found by id")
        if id_ == sel.GRID_ANEXOS and not (self.tem_grid and self.popups):
            raise com_error("The control could not be found by id")
        if id_.startswith("wnd[1]") and id_ == "wnd[1]" and not self.popups:
            raise com_error("The control could not be found by id")
        if id_ == "wnd[0]/INEXISTENTE":
            raise com_error("The control could not be found by id")
        return self.el(id_)


class DialogoFalso(DialogoArquivo):
    def __init__(self, sessao, erro=None):
        self.s, self.erro = sessao, erro

    def iniciar(self, caminho):
        self.s.eventos.append(("dialogo.iniciar", Path(caminho).name))
        t = TarefaDialogo()
        t.erro, t.concluida = self.erro, self.erro is None
        return t


@pytest.fixture
def s():
    return SessaoFalsa()


@pytest.fixture
def sap(s):
    return SapPedidos(SapNavigation(s), DialogoFalso(s), "ME22N", timeout=1)


def test_abrir_pedido_ok(s, sap):
    sap.abrir_pedido("4500001001")
    assert ("start", "ME22N") in s.eventos
    assert s.el(sel.CAMPO_PEDIDO_DIALOGO).text == "4500001001"
    assert s.popups == 0


def test_nao_reabre_transacao_se_ja_estiver_nela(s, sap):
    s.transacao = "ME22N"
    sap.abrir_pedido("4500001001")
    assert not any(e[0] == "start" for e in s.eventos)


@pytest.mark.parametrize("mensagem,exc", [
    ("Pedido 4500009999 não existe", PedidoNaoEncontradoError),
    ("Sem autorização para exibir pedidos", SemAutorizacaoError),
    ("Pedido bloqueado pelo usuário JSILVA", PedidoBloqueadoError),
    ("Erro qualquer do SAP", PedidoComErroError),
])
def test_erros_da_barra_de_status_sao_classificados_e_popup_fechado(s, sap, mensagem, exc):
    s.mensagens["4500009999"] = mensagem
    with pytest.raises(exc):
        sap.abrir_pedido("4500009999")
    assert s.popups == 0, "o diálogo precisa ser fechado para o próximo pedido começar limpo"


def test_listar_anexos_le_a_coluna_de_titulos(s, sap):
    s.anexos = ["COA_lote1", "COA_lote2"]
    assert sap.listar_anexos() == ["COA_lote1", "COA_lote2"]
    assert s.popups == 0


def test_listar_anexos_sem_grid_devolve_vazio(s, sap):
    s.tem_grid = False
    assert sap.listar_anexos() == []


def test_anexar_inicia_o_dialogo_ANTES_de_acionar_o_menu(s, sap):
    sap.anexar(Path("/tmp/COA.pdf"))
    ordem = [e[0] for e in s.eventos if e[0] in ("dialogo.iniciar", "ctx_item")]
    assert ordem == ["dialogo.iniciar", "ctx_item"]
    assert ("ctx_item", sel.GOS_CRIAR_ANEXO) in s.eventos


def test_anexar_falha_se_dialogo_nao_foi_tratado(s):
    sap = SapPedidos(SapNavigation(s), DialogoFalso(s, erro="Janela 'Abrir' não apareceu"), timeout=1)
    with pytest.raises(AnexoFalhouError, match="não apareceu"):
        sap.anexar(Path("COA.pdf"))


def test_anexar_falha_se_sap_mostra_erro(s, sap):
    s.erro_ao_criar = "Tipo de arquivo não permitido"
    with pytest.raises(AnexoFalhouError, match="não permitido"):
        sap.anexar(Path("COA.pdf"))


def test_com_error_com_sessao_viva_vira_elemento_nao_encontrado(s, sap, monkeypatch):
    monkeypatch.setattr(sel, "GOS_BARRA", "wnd[0]/INEXISTENTE")
    with pytest.raises(ElementoSapNaoEncontradoError, match="seletores.py"):
        sap.anexar(Path("COA.pdf"))


def test_com_error_com_sessao_morta_vira_sessao_perdida(s, sap):
    s.morta = True
    with pytest.raises(SessaoSapPerdidaError):
        sap.abrir_pedido("4500001001")


def test_limpar_popups_fecha_todas_as_janelas(s, sap):
    s.popups = 3
    sap.limpar_popups()
    assert [e for e in s.eventos if e[0] == "close"][0] == ("close", "wnd[3]")


def test_dialogo_sem_pywinauto_falha_com_mensagem_clara(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "pywinauto", None)  # força ImportError
    tarefa = DialogoArquivo(timeout=1).iniciar(Path("x.pdf"))
    with pytest.raises(AnexoFalhouError, match="pywinauto"):
        tarefa.aguardar(2)


# ------------------------------------------------------------------ ME22N: soltar o bloqueio ao terminar
def test_transacao_padrao_e_me22n():
    import config as cfg_mod
    assert cfg_mod.Config().transacao == "ME22N"
    assert SapPedidos(SapNavigation(SessaoFalsa()), None).transacao == "ME22N"


def test_encerrar_sai_da_transacao_para_soltar_o_bloqueio(s, sap):
    sap.abrir_pedido("4500001001")
    assert s.transacao == "ME22N"
    sap.encerrar()
    assert s.transacao == "SESSION_MANAGER" and ("start", "SESSION_MANAGER") in s.eventos


def test_encerrar_sem_ter_aberto_nada_nao_faz_nada(s, sap):
    sap.encerrar()
    assert ("start", "SESSION_MANAGER") not in s.eventos


def test_encerrar_nunca_levanta_mesmo_com_sessao_morta(s, sap):
    sap.abrir_pedido("4500001001")
    s.morta = True
    sap.encerrar()          # não pode derrubar a execução (log de aviso apenas)
