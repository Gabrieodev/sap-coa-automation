"""Janelas do Windows que aparecem em 'Criar anexo' (ME22N > Serviços para objeto > Criar > Criar anexo).

Duas janelas nativas, fora da árvore de scripting do SAP:
  1. "Abrir": escolher o arquivo (preencher o caminho e confirmar);
  2. "Segurança do SAP GUI": o SAP GUI avisa que vai acessar um arquivo local -> botão "Permitir".
A ordem entre elas pode variar e a 2ª pode nem aparecer (se alguém marcou "lembrar minha decisão"),
então uma única rotina observa as janelas e trata o que surgir.

Por que existe uma thread: quando o SAP abre a janela modal, a chamada de scripting que a abriu
(selectContextMenuItem) FICA BLOQUEADA até a janela fechar. O tratamento das janelas precisa rodar
em paralelo, ANTES de disparar o menu no SAP.

Requer `pywinauto` (apenas Windows). Títulos dependem do idioma do Windows/SAP; ajuste as
expressões abaixo se necessário (scripts/listar_janelas.py mostra os títulos reais).
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from src.erros import AnexoFalhouError

TITULO_RE = r"(?i)^(abrir|open|selecionar.*|select.*|escolher.*|choose.*)$"
BOTAO_RE = r"(?i)^&?(abrir|open)$"
# "SAP GUI Security" (EN) / "Segurança do SAP GUI" (PT)
TITULO_SEGURANCA_RE = r"(?i)(sap\s*gui.*(security|seguran[cç]a)|(security|seguran[cç]a).*sap\s*gui)"
BOTAO_PERMITIR_RE = r"(?i)^&?(permitir|allow)$"


@dataclass(frozen=True)
class JanelaInfo:
    handle: int
    titulo: str
    classe: str


class AdaptadorPywinauto:
    """Única parte que conhece o pywinauto (import tardio: só existe no Windows)."""

    def __init__(self):
        from pywinauto import Desktop  # ImportError tratado por quem chama
        self._desktop = Desktop

    def janelas(self) -> list[JanelaInfo]:
        return [JanelaInfo(w.handle, w.window_text() or "", w.class_name() or "")
                for w in self._desktop(backend="win32").windows(visible_only=True)]

    def preencher_e_abrir(self, handle: int, caminho: Path) -> None:
        dlg = self._desktop(backend="win32").window(handle=handle)
        edit = dlg.child_window(class_name="Edit", found_index=0)
        edit.set_edit_text(str(caminho.resolve()))
        try:
            dlg.child_window(class_name="Button", title_re=BOTAO_RE).click()
        except Exception:
            edit.type_keys("{ENTER}")

    def clicar_botao(self, handle: int, botao_re: str) -> bool:
        try:
            dlg = self._desktop(backend="win32").window(handle=handle)
            dlg.child_window(class_name="Button", title_re=botao_re).click()
            return True
        except Exception:
            return False


class TarefaDialogo:
    def __init__(self):
        self.thread: threading.Thread | None = None
        self.erro: str | None = None
        self.concluida = False
        self.seguranca_tratada = False   # clicou em "Permitir"

    def aguardar(self, timeout: float = 10):
        if self.thread:
            self.thread.join(timeout)
        if self.erro:
            raise AnexoFalhouError(self.erro)
        if not self.concluida:
            raise AnexoFalhouError("Janelas de seleção de arquivo/segurança não foram tratadas a tempo")


class DialogoArquivo:
    def __init__(self, timeout: int = 20, titulo_re: str = TITULO_RE, espera_seguranca: float = 3.0,
                 adaptador=None, titulo_seguranca_re: str = TITULO_SEGURANCA_RE,
                 botao_permitir_re: str = BOTAO_PERMITIR_RE, intervalo: float = 0.3):
        self.timeout = timeout
        self.titulo_re = titulo_re
        self.espera_seguranca = espera_seguranca
        self.titulo_seguranca_re = titulo_seguranca_re
        self.botao_permitir_re = botao_permitir_re
        self.intervalo = intervalo
        self._adaptador = adaptador
        # o aviso de segurança apareceu no anexo anterior? (None = ainda não sabemos)
        self._seguranca_vista: bool | None = None

    def _espera_atual(self) -> float:
        """Quanto esperar pelo aviso de segurança depois de escolher o arquivo. Se ele não
        apareceu no anexo anterior (decisão lembrada), espera pouco: não perde tempo em 40 arquivos."""
        return self.espera_seguranca if self._seguranca_vista in (None, True) else min(self.espera_seguranca, 1.0)

    def iniciar(self, caminho: Path) -> TarefaDialogo:
        """Dispara a thread que vai observar as janelas e tratá-las."""
        tarefa = TarefaDialogo()
        tarefa.thread = threading.Thread(target=self._rodar, args=(Path(caminho), tarefa), daemon=True)
        tarefa.thread.start()
        return tarefa

    def _rodar(self, caminho: Path, tarefa: TarefaDialogo) -> None:
        try:
            ad = self._adaptador or AdaptadorPywinauto()
        except ImportError:
            tarefa.erro = "pywinauto não instalado (pip install pywinauto)"
            return
        try:
            re_arquivo = re.compile(self.titulo_re)
            re_seguranca = re.compile(self.titulo_seguranca_re)
            fim = time.monotonic() + self.timeout
            arquivo_ok = seguranca_ok = seguranca_vista = False
            limite_seguranca: float | None = None
            while time.monotonic() < fim:
                for w in ad.janelas():
                    if not seguranca_ok and re_seguranca.search(w.titulo):
                        seguranca_vista = True
                        seguranca_ok = ad.clicar_botao(w.handle, self.botao_permitir_re)
                    elif not arquivo_ok and w.classe == "#32770" and re_arquivo.match(w.titulo):
                        ad.preencher_e_abrir(w.handle, caminho)
                        arquivo_ok = True
                        limite_seguranca = time.monotonic() + self._espera_atual()
                if arquivo_ok and (seguranca_ok or time.monotonic() >= (limite_seguranca or 0)):
                    break
                time.sleep(self.intervalo)
            tarefa.seguranca_tratada = seguranca_ok
            if seguranca_vista and not seguranca_ok:
                tarefa.erro = ("O aviso 'Segurança do SAP GUI' apareceu, mas não consegui clicar em "
                               "'Permitir' (ajuste botao_permitir_re em dialogo_arquivo.py)")
            elif not arquivo_ok:
                tarefa.erro = f"Janela 'Abrir' não apareceu em {self.timeout}s"
            else:
                self._seguranca_vista = seguranca_vista
                tarefa.concluida = True
        except Exception as e:  # nunca deixar a thread morrer em silêncio
            tarefa.erro = f"Falha ao tratar janelas do anexo: {type(e).__name__}: {e}"
