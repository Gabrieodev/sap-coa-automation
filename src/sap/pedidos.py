"""Operações do robô sobre um pedido na ME23N: abrir, listar anexos, anexar.

É a ÚNICA classe que conhece telas e IDs do SAP. O restante do robô só enxerga estes
quatro métodos, o que permite trocar por `SapSimulado` nos testes.
"""
from __future__ import annotations

import functools
from pathlib import Path

from src.erros import AnexoFalhouError, ErroDeItem, ErroFatal
from src.sap import seletores as sel
from src.sap.dialogo_arquivo import DialogoArquivo
from src.sap.exceptions import (ElementoSapNaoEncontradoError, PedidoBloqueadoError,
                                PedidoComErroError, PedidoNaoEncontradoError,
                                SemAutorizacaoError, SessaoSapPerdidaError)
from src.sap.navegacao import SapNavigation


def _traduzir_com_error(func):
    """com_error do SAP vira erro tipado: sessão perdida (fatal) ou elemento não encontrado."""
    @functools.wraps(func)
    def interno(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except (ErroDeItem, ErroFatal):
            raise
        except Exception as e:
            if type(e).__name__ != "com_error":
                raise
            if not self.nav.sessao_viva():
                raise SessaoSapPerdidaError(f"Sessão SAP não responde: {e}") from e
            raise ElementoSapNaoEncontradoError(
                f"{func.__name__}: elemento não encontrado ({e}). Revise src/sap/seletores.py"
            ) from e
    return interno


def _classificar_erro_status(texto: str, pedido: str) -> Exception:
    t = texto.lower()
    if any(k in t for k in ("não existe", "nao existe", "does not exist", "not exist")):
        return PedidoNaoEncontradoError(f"Pedido {pedido} não existe: {texto}")
    if any(k in t for k in ("autoriza", "authori")):
        return SemAutorizacaoError(f"Sem autorização para o pedido {pedido}: {texto}")
    if any(k in t for k in ("bloquead", "sendo processad", "locked", "being processed")):
        return PedidoBloqueadoError(f"Pedido {pedido} bloqueado: {texto}")
    return PedidoComErroError(f"SAP recusou o pedido {pedido}: {texto}")


class SapPedidos:
    def __init__(self, nav: SapNavigation, dialogo: DialogoArquivo,
                 transacao: str = "ME23N", timeout: int = 30,
                 coluna_titulo_anexos: str = "BITM_DESCR", log=None):
        self.nav = nav
        self.dialogo = dialogo
        self.transacao = transacao
        self.timeout = timeout
        self.coluna_titulo = coluna_titulo_anexos
        self.log = log

    # ------------------------------------------------------------------ abrir
    @_traduzir_com_error
    def abrir_pedido(self, numero: str) -> None:
        self.limpar_popups()
        if self.nav.transacao_atual() != self.transacao:
            self.nav.abrir_transacao(self.transacao)
            self.nav.aguardar(self.timeout)

        # a ME23N às vezes já abre o diálogo "Outro pedido" sozinha
        if not self.nav.existe(sel.CAMPO_PEDIDO_DIALOGO):
            self.nav.obter(sel.BTN_OUTRO_PEDIDO).press()
            self.nav.aguardar(self.timeout)

        self.nav.obter(sel.CAMPO_PEDIDO_DIALOGO).text = numero
        self.nav.obter("wnd[1]").sendVKey(0)
        self.nav.aguardar(self.timeout)

        tipo, texto = self.nav.status_barra()
        if tipo in ("E", "A") or self.nav.existe(sel.CAMPO_PEDIDO_DIALOGO):
            erro = _classificar_erro_status(texto or "(sem mensagem)", numero)
            self.limpar_popups()
            raise erro

    # ----------------------------------------------------------------- anexos
    @_traduzir_com_error
    def listar_anexos(self) -> list[str]:
        """Títulos dos anexos do pedido aberto (como aparecem na lista do SAP)."""
        self.nav.clicar_menu_contexto(sel.GOS_BARRA, sel.GOS_MENU, sel.GOS_LISTA_ANEXOS)
        self.nav.aguardar(self.timeout)
        if not self.nav.existe(sel.GRID_ANEXOS):
            self.limpar_popups()
            return []  # sem lista = sem anexos (VALIDAR no seu ambiente)
        grid = self.nav.obter(sel.GRID_ANEXOS)
        nomes = [str(grid.GetCellValue(i, self.coluna_titulo)) for i in range(int(grid.RowCount))]
        self.limpar_popups()
        return nomes

    @_traduzir_com_error
    def anexar(self, caminho: Path) -> None:
        # 1) a thread precisa estar de pé ANTES de abrir a janela (ver dialogo_arquivo.py)
        tarefa = self.dialogo.iniciar(caminho)
        # 2) Serviços para objeto > Criar > Criar anexo (bloqueia até a janela fechar)
        self.nav.clicar_menu_contexto(sel.GOS_BARRA, sel.GOS_MENU, sel.GOS_CRIAR_ANEXO)
        tarefa.aguardar(timeout=self.timeout)
        self.nav.aguardar(self.timeout)
        tipo, texto = self.nav.status_barra()
        if tipo in ("E", "A"):
            raise AnexoFalhouError(f"SAP recusou o anexo '{Path(caminho).name}': {texto}")

    # ----------------------------------------------------------------- limpeza
    def limpar_popups(self, max_tentativas: int = 5) -> None:
        """Fecha janelas modais pendentes para o próximo pedido começar de tela limpa."""
        for _ in range(max_tentativas):
            n = self.nav.popups_abertos()
            if n == 0:
                return
            try:
                self.nav.fechar_janela(n)
                self.nav.aguardar(5)
            except Exception:
                return
