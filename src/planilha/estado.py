"""Registro do que o robô já processou, em CSV separado da planilha de controle.

Motivo: a planilha de produção é compartilhada com outras pessoas. Reescrevê-la via openpyxl
arrisca perder formatação/filtros/macros e falha se alguém estiver com ela aberta. O robô
então só LÊ a planilha e guarda o próprio andamento aqui (chave = pedido + processo).
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

CAMPOS = ["pedido", "processo", "status", "data_processamento", "observacao"]


def _chave(pedido: str, processo: str) -> str:
    return f"{pedido}|{processo}"


class EstadoCsv:
    def __init__(self, caminho: Path, log=None):
        self.caminho = Path(caminho)
        self.log = log
        self._dados: dict[str, dict[str, str]] = {}
        self._sujo = False
        self._carregar()

    def _carregar(self) -> None:
        if not self.caminho.exists():
            return
        with open(self.caminho, newline="", encoding="utf-8-sig") as f:
            for linha in csv.DictReader(f, delimiter=";"):
                self._dados[_chave(linha.get("pedido", ""), linha.get("processo", ""))] = linha

    def obter(self, pedido: str, processo: str) -> tuple[str, str] | None:
        reg = self._dados.get(_chave(pedido, processo))
        return (reg.get("status", ""), reg.get("observacao", "")) if reg else None

    def registrar(self, pedido: str, processo: str, status: str, observacao: str = "") -> None:
        self._dados[_chave(pedido, processo)] = {
            "pedido": pedido, "processo": processo, "status": status,
            "data_processamento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "observacao": observacao[:500],
        }
        self._sujo = True

    def salvar(self) -> bool:
        """Grava de forma atômica (arquivo temporário + replace). False se o arquivo estiver
        travado (ex.: aberto no Excel); os dados continuam em memória para nova tentativa."""
        if not self._sujo:
            return True
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.caminho.with_suffix(self.caminho.suffix + ".tmp")
        try:
            with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=CAMPOS, delimiter=";")
                w.writeheader()
                w.writerows(self._dados.values())
            os.replace(tmp, self.caminho)
        except PermissionError:
            if self.log:
                self.log.warning("Arquivo de estado travado (aberto em outro programa?): %s",
                                 self.caminho)
            return False
        self._sujo = False
        return True
