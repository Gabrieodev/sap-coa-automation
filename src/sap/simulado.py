"""SAP de mentirinha para desenvolver e testar sem SAP GUI (qualquer SO).

Expõe a mesma interface de `SapPedidos`. Cenários de erro são injetados no construtor.
"""
from __future__ import annotations

from pathlib import Path

from src.sap.exceptions import (PedidoBloqueadoError, PedidoNaoEncontradoError,
                                SemAutorizacaoError, SessaoSapPerdidaError)
from src.erros import AnexoFalhouError


class SapSimulado:
    def __init__(self, inexistentes=(), bloqueados=(), sem_autorizacao=(),
                 anexos_iniciais: dict[str, list[str]] | None = None,
                 falha_anexo=(), nao_confirma=(), cai_no_pedido: str | None = None):
        self.inexistentes = set(inexistentes)
        self.bloqueados = set(bloqueados)
        self.sem_autorizacao = set(sem_autorizacao)
        self.falha_anexo = set(falha_anexo)      # nomes de arquivo cujo upload falha sempre
        self.nao_confirma = set(nao_confirma)    # pedidos em que o anexo "some" da lista
        self.cai_no_pedido = cai_no_pedido       # simula sessão SAP morrendo neste pedido
        # como no SAP real, guardamos o TÍTULO (sem extensão)
        self.anexos: dict[str, list[str]] = {p: list(v) for p, v in (anexos_iniciais or {}).items()}
        self.atual: str | None = None
        self.chamadas: list[tuple] = []

    def abrir_pedido(self, numero: str) -> None:
        self.chamadas.append(("abrir", numero))
        if numero == self.cai_no_pedido:
            raise SessaoSapPerdidaError("SAP simulado: sessão perdida")
        if numero in self.inexistentes:
            raise PedidoNaoEncontradoError(f"Pedido {numero} não existe (simulado)")
        if numero in self.bloqueados:
            raise PedidoBloqueadoError(f"Pedido {numero} bloqueado pelo usuário XYZ (simulado)")
        if numero in self.sem_autorizacao:
            raise SemAutorizacaoError(f"Sem autorização para o pedido {numero} (simulado)")
        self.atual = numero
        self.anexos.setdefault(numero, [])

    def listar_anexos(self) -> list[str]:
        self.chamadas.append(("listar", self.atual))
        return list(self.anexos[self.atual])

    def anexar(self, caminho: Path) -> None:
        self.chamadas.append(("anexar", self.atual, Path(caminho).name))
        if Path(caminho).name in self.falha_anexo:
            raise AnexoFalhouError(f"Falha simulada ao anexar {Path(caminho).name}")
        if self.atual not in self.nao_confirma:
            self.anexos[self.atual].append(Path(caminho).stem)

    def limpar_popups(self) -> None:
        self.chamadas.append(("limpar",))
