from __future__ import annotations

from dataclasses import dataclass, field

PENDENTE = "PENDENTE"
CONCLUIDO = "CONCLUIDO"
ERRO = "ERRO"
IGNORADO = "IGNORADO"
DRY_RUN = "DRY_RUN"  # só aparece no relatório CSV, nunca na planilha


@dataclass
class ItemControle:
    """Uma linha da planilha de controle."""
    linha: int
    pedido: str
    processo: str
    status: str = ""
    observacao: str = ""
    erro_validacao: str | None = None  # preenchido pela leitura se a linha é inválida
    duplicado: bool = False            # cópia exata de outra linha (mesmo pedido+processo)

    def deve_processar(self, reprocessar_erros: bool = False) -> bool:
        s = (self.status or "").strip().upper()
        if s in ("", PENDENTE):
            return True
        return reprocessar_erros and s == ERRO


@dataclass
class Resultado:
    item: ItemControle
    status: str
    mensagem: str = ""
    anexados: list[str] = field(default_factory=list)
    ja_existiam: list[str] = field(default_factory=list)
    duracao_s: float = 0.0
