"""Operacoes do robo sobre um pedido na ME22N.

Responsabilidades:

1. Abrir um pedido na ME22N;
2. Listar os anexos do pedido aberto;
3. Acionar Servicos para objeto > Criar > Criar anexo;
4. Solicitar ao DialogoArquivo o tratamento das janelas de anexo;
5. Encerrar a ME22N para liberar o bloqueio do ultimo pedido.

Esta e a unica classe que conhece as telas e os IDs do SAP relacionados
aos pedidos. O restante do robo usa apenas os metodos publicos desta
classe, permitindo substituir SapPedidos por SapSimulado nos testes.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any

from src.erros import AnexoFalhouError, ErroDeItem, ErroFatal
from src.sap import seletores as sel
from src.sap.dialogo_arquivo import DialogoArquivo
from src.sap.exceptions import (
    ElementoSapNaoEncontradoError,
    PedidoBloqueadoError,
    PedidoComErroError,
    PedidoNaoEncontradoError,
    SemAutorizacaoError,
    SessaoSapPerdidaError,
)
from src.sap.navegacao import SapNavigation


def _traduzir_com_error(func):
    """Converte com_error do SAP em erros especificos do robo."""

    @functools.wraps(func)
    def interno(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except (ErroDeItem, ErroFatal):
            raise
        except Exception as exc:
            if type(exc).__name__ != "com_error":
                raise

            if not self.nav.sessao_viva():
                raise SessaoSapPerdidaError(
                    f"Sessao SAP nao responde: {exc}"
                ) from exc

            raise ElementoSapNaoEncontradoError(
                f"{func.__name__}: elemento SAP nao encontrado "
                f"({exc}). Revise src/sap/seletores.py."
            ) from exc

    return interno


def _classificar_erro_status(texto: str, pedido: str) -> Exception:
    """Converte uma mensagem da barra de status em erro especifico."""

    texto_normalizado = texto.lower()

    if any(
        termo in texto_normalizado
        for termo in (
            "nao existe",
            "não existe",
            "does not exist",
            "not exist",
        )
    ):
        return PedidoNaoEncontradoError(
            f"Pedido {pedido} nao existe: {texto}"
        )

    if any(
        termo in texto_normalizado
        for termo in ("autoriza", "authori")
    ):
        return SemAutorizacaoError(
            f"Sem autorizacao para o pedido {pedido}: {texto}"
        )

    if any(
        termo in texto_normalizado
        for termo in (
            "bloquead",
            "sendo processad",
            "locked",
            "being processed",
        )
    ):
        return PedidoBloqueadoError(
            f"Pedido {pedido} bloqueado: {texto}"
        )

    return PedidoComErroError(
        f"SAP recusou o pedido {pedido}: {texto}"
    )


class SapPedidos:
    """Executa operacoes de pedido na transacao ME22N."""

    def __init__(
        self,
        nav: SapNavigation,
        dialogo: DialogoArquivo,
        transacao: str = "ME22N",
        timeout: int = 50,
        coluna_titulo_anexos: str = "BITM_DESCR",
        log=None,
    ) -> None:
        self.nav = nav
        self.dialogo = dialogo
        self.transacao = transacao
        self.timeout = timeout
        self.coluna_titulo = coluna_titulo_anexos
        self.log = log
        # True quando a ultima listar_anexos() conseguiu LER a tabela (mesmo vazia). False = a tabela
        # nao foi encontrada: o resultado [] nao significa "sem anexos". Usado pelo processador.
        self.ultima_lista_legivel = True
        self._criar_anexo_itens = list(
            sel.GOS_CRIAR_ANEXO_ALTERNATIVAS
        )

    @_traduzir_com_error
    def abrir_pedido(self, numero: str) -> None:
        """Abre um pedido na ME22N."""

        numero = str(numero).strip()
        if not numero:
            raise PedidoComErroError(
                "O numero do pedido SAP esta vazio."
            )

        self.limpar_popups()

        if self.nav.transacao_atual() != self.transacao:
            self.nav.abrir_transacao(self.transacao)
            self.nav.aguardar(self.timeout)

        if not self.nav.existe(sel.CAMPO_PEDIDO_DIALOGO):
            self.nav.obter(sel.BTN_OUTRO_PEDIDO).press()
            self.nav.aguardar(self.timeout)

        campo_pedido = self.nav.obter(sel.CAMPO_PEDIDO_DIALOGO)
        campo_pedido.text = numero
        self.nav.obter("wnd[1]").sendVKey(0)
        self.nav.aguardar(self.timeout)

        tipo, texto = self.nav.status_barra()
        dialogo_aberto = self.nav.existe(sel.CAMPO_PEDIDO_DIALOGO)

        if tipo in ("E", "A") or dialogo_aberto:
            mensagem = texto or "(sem mensagem na barra de status)"
            erro = _classificar_erro_status(mensagem, numero)
            self.limpar_popups()
            raise erro

        if self.log:
            self.log.info(
                "Pedido %s aberto na transacao %s.",
                numero,
                self.transacao,
            )

    @_traduzir_com_error
    def listar_anexos(self) -> list[str]:
        """Retorna os titulos dos anexos do pedido aberto."""

        self.ultima_lista_legivel = False
        self.nav.clicar_menu_contexto(
            sel.GOS_BARRA,
            sel.GOS_MENU,
            sel.GOS_LISTA_ANEXOS,
        )
        self.nav.aguardar(self.timeout)

        if self.nav.existe(sel.GRID_ANEXOS):
            grid = self.nav.obter(sel.GRID_ANEXOS)
        else:
            grid = self.nav.achar_grid("wnd[1]/usr")

        if grid is None:
            if self.log:
                if self.nav.existe("wnd[1]"):
                    motivo = (
                        "a janela abriu, mas nenhuma tabela de anexos "
                        "foi encontrada"
                    )
                else:
                    motivo = "nenhuma janela de anexos foi aberta"

                self.log.warning(
                    "Lista de anexos: %s; considerando pedido sem anexos.",
                    motivo,
                )

            self.limpar_popups()
            return []

        nomes = self._titulos_da_tabela(grid)
        self.ultima_lista_legivel = True
        self.limpar_popups()

        if self.log:
            self.log.info(
                "Lista de anexos lida: %d anexo(s).",
                len(nomes),
            )

        return nomes

    def _titulos_da_tabela(self, grid: Any) -> list[str]:
        """Le a coluna de titulos da tabela de anexos."""

        quantidade_linhas = int(grid.RowCount)

        try:
            return [
                str(
                    grid.GetCellValue(
                        indice,
                        self.coluna_titulo,
                    )
                ).strip()
                for indice in range(quantidade_linhas)
            ]
        except Exception as primeiro_erro:
            try:
                colunas = [
                    str(coluna)
                    for coluna in _como_lista(grid.ColumnOrder)
                ]

                if not colunas:
                    raise primeiro_erro

                coluna_escolhida = colunas[0]

                for coluna in colunas:
                    titulos = _como_lista(
                        grid.GetColumnTitles(coluna)
                    )
                    cabecalho = " ".join(
                        str(titulo) for titulo in titulos
                    )

                    if re.search(
                        r"(?i)t[ií]tulo|title|nome|name|descri",
                        cabecalho,
                    ):
                        coluna_escolhida = coluna
                        break

                if self.log:
                    self.log.info(
                        "Lista de anexos: coluna configurada %r nao "
                        "existe. Colunas encontradas=%s; usando %r. "
                        "Ajuste coluna_titulo_anexos se necessario.",
                        self.coluna_titulo,
                        colunas,
                        coluna_escolhida,
                    )

                return [
                    str(
                        grid.GetCellValue(
                            indice,
                            coluna_escolhida,
                        )
                    ).strip()
                    for indice in range(quantidade_linhas)
                ]
            except Exception:
                raise primeiro_erro

    @_traduzir_com_error
    def anexar(self, caminho: Path) -> None:
        """Anexa um arquivo ao pedido atualmente aberto na ME22N."""

        caminho = Path(caminho).expanduser().resolve()

        if not caminho.is_file():
            raise AnexoFalhouError(
                f"Arquivo nao encontrado para anexar: {caminho}"
            )

        try:
            with caminho.open("rb") as arquivo:
                arquivo.read(1)
        except OSError as exc:
            raise AnexoFalhouError(
                "O arquivo existe, mas nao esta disponivel para leitura. "
                "Verifique se o documento do SharePoint/OneDrive esta "
                "baixado neste dispositivo e se nao esta bloqueado. "
                f"Arquivo: {caminho}. "
                f"Erro: {type(exc).__name__}: {exc}"
            ) from exc

        if self.log:
            try:
                tamanho = caminho.stat().st_size
            except OSError:
                tamanho = -1

            self.log.info(
                "Iniciando anexo no SAP: arquivo=%r; tamanho=%d bytes.",
                str(caminho),
                tamanho,
            )

        tarefa = self.dialogo.iniciar(caminho)

        try:
            usado = self.nav.clicar_menu_contexto_com_alternativas(
                sel.GOS_BARRA,
                sel.GOS_MENU,
                self._criar_anexo_itens,
            )
        except Exception:
            cancelar = getattr(tarefa, "cancelar", None)
            if cancelar is not None:
                cancelar()
            raise

        if (
            self._criar_anexo_itens
            and usado != self._criar_anexo_itens[0]
        ):
            if self.log:
                self.log.info(
                    "'Criar anexo' acionado pelo item %r. "
                    "O primeiro item configurado nao funcionou.",
                    usado,
                )

            if usado in self._criar_anexo_itens:
                self._criar_anexo_itens.remove(usado)
            self._criar_anexo_itens.insert(0, usado)

        tarefa.aguardar(timeout=self.timeout)
        self.nav.aguardar(self.timeout)

        tipo, texto = self.nav.status_barra()
        if tipo in ("E", "A"):
            mensagem = texto or "(sem mensagem na barra de status)"
            raise AnexoFalhouError(
                f"SAP recusou o anexo '{caminho.name}': {mensagem}"
            )

        if self.log:
            self.log.info(
                "Arquivo anexado ao pedido: %s",
                caminho.name,
            )

    def encerrar(self) -> None:
        """Sai da ME22N com /n e libera o bloqueio do ultimo pedido."""

        try:
            self.limpar_popups()

            if self.nav.transacao_atual() != self.transacao:
                return

            campo_comando = self.nav.obter(
                "wnd[0]/tbar[0]/okcd"
            )
            campo_comando.text = "/n"
            self.nav.obter("wnd[0]").sendVKey(0)
            self.nav.aguardar(self.timeout)

            if self.log:
                self.log.info(
                    "Transacao %s encerrada para liberar o pedido.",
                    self.transacao,
                )
        except Exception as exc:
            if self.log:
                self.log.warning(
                    "Nao consegui sair da transacao %s ao terminar. "
                    "O ultimo pedido pode permanecer bloqueado ate a "
                    "sessao SAP ser fechada: %s",
                    self.transacao,
                    exc,
                )

    def limpar_popups(self, max_tentativas: int = 5) -> None:
        """Fecha janelas modais SAP antes do proximo pedido."""

        for _ in range(max_tentativas):
            try:
                quantidade = self.nav.popups_abertos()
            except Exception:
                return

            if quantidade == 0:
                return

            try:
                self.nav.fechar_janela(quantidade)
                self.nav.aguardar(5)
            except Exception:
                return


def _como_lista(colecao: Any) -> list:
    """Converte uma colecao COM do SAP ou iteravel comum em lista."""

    try:
        quantidade = int(colecao.Count)
        return [
            colecao.ElementAt(indice)
            for indice in range(quantidade)
        ]
    except Exception:
        try:
            return list(colecao)
        except Exception:
            return []