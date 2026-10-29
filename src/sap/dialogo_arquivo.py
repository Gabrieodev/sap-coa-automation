"""Automação da janela "Abrir" nativa do Windows que o SAP mostra em 'Criar anexo'.

Por que existe uma thread: quando o SAP abre essa janela modal, a chamada de scripting
que a abriu (selectContextMenuItem) FICA BLOQUEADA até a janela fechar. Então o
preenchimento precisa rodar em paralelo, ANTES de disparar o menu no SAP.

Requer `pywinauto` (apenas Windows). O título da janela depende do idioma do Windows/SAP;
ajuste `titulo_re` se necessário.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from src.erros import AnexoFalhouError

TITULO_RE = r"(?i)^(abrir|open|selecionar.*|select.*|escolher.*|choose.*)$"
BOTAO_RE = r"(?i)^&?(abrir|open)$"


class TarefaDialogo:
    def __init__(self):
        self.thread: threading.Thread | None = None
        self.erro: str | None = None
        self.concluida = False

    def aguardar(self, timeout: float = 10):
        if self.thread:
            self.thread.join(timeout)
        if self.erro:
            raise AnexoFalhouError(self.erro)
        if not self.concluida:
            raise AnexoFalhouError("Janela de seleção de arquivo não foi tratada a tempo")


class DialogoArquivo:
    def __init__(self, timeout: int = 20, titulo_re: str = TITULO_RE):
        self.timeout = timeout
        self.titulo_re = titulo_re

    def iniciar(self, caminho: Path) -> TarefaDialogo:
        """Dispara a thread que vai esperar a janela aparecer e preenchê-la."""
        tarefa = TarefaDialogo()
        tarefa.thread = threading.Thread(target=self._rodar, args=(Path(caminho), tarefa), daemon=True)
        tarefa.thread.start()
        return tarefa

    def _rodar(self, caminho: Path, tarefa: TarefaDialogo) -> None:
        try:
            from pywinauto import Desktop  # import tardio (só existe no Windows)
        except ImportError:
            tarefa.erro = "pywinauto não instalado (pip install pywinauto)"
            return
        try:
            padrao = re.compile(self.titulo_re)
            fim = time.monotonic() + self.timeout
            while time.monotonic() < fim:
                for w in Desktop(backend="win32").windows(class_name="#32770", visible_only=True):
                    if not padrao.match(w.window_text() or ""):
                        continue
                    dlg = Desktop(backend="win32").window(handle=w.handle)
                    edit = dlg.child_window(class_name="Edit", found_index=0)
                    edit.set_edit_text(str(caminho.resolve()))
                    try:
                        dlg.child_window(class_name="Button", title_re=BOTAO_RE).click()
                    except Exception:
                        edit.type_keys("{ENTER}")
                    tarefa.concluida = True
                    return
                time.sleep(0.3)
            tarefa.erro = f"Janela 'Abrir' não apareceu em {self.timeout}s"
        except Exception as e:  # nunca deixar a thread morrer em silêncio
            tarefa.erro = f"Falha ao preencher janela de arquivo: {type(e).__name__}: {e}"
