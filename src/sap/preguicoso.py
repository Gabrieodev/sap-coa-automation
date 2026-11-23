"""Conexão ao SAP sob demanda.

Numa execução diária agendada, muitos dias não têm nada a anexar (todas as linhas já estão
'JÁ ANEXADO'). Conectar ao SAP na partida faria o robô falhar à toa se o SAP estiver fechado e
gastaria tempo sem necessidade. Aqui a conexão só é criada quando o primeiro pedido realmente
precisar abrir o SAP; linhas que falham antes disso (pasta ausente, dados inválidos) também não
conectam.
"""
from __future__ import annotations

from pathlib import Path


class SapPreguicoso:
    def __init__(self, fabrica, log=None):
        self._fabrica = fabrica      # função que conecta e devolve o SapPedidos real
        self._real = None
        self._log = log

    @property
    def conectado(self) -> bool:
        return self._real is not None

    def _sap(self):
        if self._real is None:
            if self._log:
                self._log.info("Conectando ao SAP (primeiro pedido que precisa dele)...")
            self._real = self._fabrica()  # pode levantar SapNaoAbertoError/SapNaoLogadoError (fatais)
        return self._real

    def abrir_pedido(self, numero: str) -> None:
        self._sap().abrir_pedido(numero)

    def listar_anexos(self) -> list[str]:
        return self._sap().listar_anexos()

    def anexar(self, caminho: Path) -> None:
        self._sap().anexar(caminho)

    def encerrar(self) -> None:
        if self._real is not None:   # nunca conecta só para encerrar
            self._real.encerrar()

    def limpar_popups(self) -> None:
        if self._real is not None:   # nunca conecta só para limpar tela
            self._real.limpar_popups()
