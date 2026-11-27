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
                 falha_anexo=(), nao_confirma=(), cai_no_pedido: str | None = None,
                 lista_ilegivel: bool = False, titulo_na_lista: str | None = None,
                 falha_depois_de_anexar=()):
        self.inexistentes = set(inexistentes)
        self.bloqueados = set(bloqueados)
        self.sem_autorizacao = set(sem_autorizacao)
        self.falha_anexo = set(falha_anexo)      # nomes de arquivo cujo upload falha sempre
        self.nao_confirma = set(nao_confirma)    # pedidos em que o anexo "some" da lista
        self.cai_no_pedido = cai_no_pedido       # simula sessão SAP morrendo neste pedido
        # como no SAP real, guardamos o TÍTULO (sem extensão)
        self.anexos: dict[str, list[str]] = {p: list(v) for p, v in (anexos_iniciais or {}).items()}
        self.lista_ilegivel = lista_ilegivel          # tabela de anexos não encontrada: devolve []
        self.titulo_na_lista = titulo_na_lista        # título diferente do nome do arquivo (ex.: "PDF")
        self.falha_depois_de_anexar = set(falha_depois_de_anexar)  # anexa, mas acusa erro na 1ª vez
        self._ja_falhou: set[str] = set()
        self.ultima_lista_legivel = True
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
        self.ultima_lista_legivel = not self.lista_ilegivel
        if self.lista_ilegivel:
            return []
        return list(self.anexos[self.atual])

    def anexar(self, caminho: Path) -> None:
        self.chamadas.append(("anexar", self.atual, Path(caminho).name))
        if Path(caminho).name in self.falha_anexo:
            raise AnexoFalhouError(f"Falha simulada ao anexar {Path(caminho).name}")
        if self.atual not in self.nao_confirma:
            self.anexos[self.atual].append(self.titulo_na_lista or Path(caminho).stem)
        nome = Path(caminho).name
        if nome in self.falha_depois_de_anexar and nome not in self._ja_falhou:
            self._ja_falhou.add(nome)
            raise AnexoFalhouError(f"Falha simulada DEPOIS de anexar {nome} (ex.: janela demorou)")

    def encerrar(self) -> None:
        if self.atual is not None:       # como o real: só sai da transação se chegou a abrir pedido
            self.chamadas.append(("encerrar",))

    def limpar_popups(self) -> None:
        self.chamadas.append(("limpar",))
