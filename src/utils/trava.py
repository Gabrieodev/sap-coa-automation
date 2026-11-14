"""Trava de execução: impede dois robôs ao mesmo tempo (ex.: tarefa agendada + execução manual).

Dois robôs dividiriam a mesma sessão do SAP GUI e gravariam na mesma base. A trava é um arquivo
criado de forma exclusiva; se o robô morrer sem apagá-lo (queda de energia, tarefa interrompida),
o arquivo é tratado como abandonado depois de `validade_horas`.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path


class ExecucaoEmAndamentoError(Exception):
    """Já existe outra execução do robô em andamento."""


class TravaExecucao:
    def __init__(self, caminho: Path, validade_horas: float = 3):
        self.caminho = Path(caminho)
        self.validade_s = validade_horas * 3600
        self._minha = False

    def adquirir(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        for tentativa in range(2):
            try:
                fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if tentativa == 0 and self._abandonada():
                    try:
                        self.caminho.unlink()
                    except OSError:
                        pass
                    continue
                raise ExecucaoEmAndamentoError(self._descricao()) from None
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"pid={os.getpid()} inicio={datetime.now():%Y-%m-%d %H:%M:%S}\n")
            self._minha = True
            return

    def liberar(self) -> None:
        if self._minha:
            try:
                self.caminho.unlink()
            except OSError:
                pass
            self._minha = False

    def _abandonada(self) -> bool:
        try:
            return time.time() - self.caminho.stat().st_mtime > self.validade_s
        except OSError:
            return True  # sumiu entre a checagem e agora

    def _descricao(self) -> str:
        try:
            detalhe = self.caminho.read_text(encoding="utf-8").strip()
        except OSError:
            detalhe = "sem detalhes"
        return (f"Já existe outra execução do robô em andamento ({detalhe}). Se ela travou, apague "
                f"{self.caminho} (a trava expira sozinha após {self.validade_s / 3600:g} h).")
