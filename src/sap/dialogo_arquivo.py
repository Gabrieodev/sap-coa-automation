"""Tratamento das janelas exibidas ao criar um anexo na ME22N.

Fluxo:
1. O SAP GUI abre a janela "Importar file";
2. O robo preenche Diretorio e Nome file;
3. O robo confirma a janela;
4. O SAP GUI pode exibir a janela "Seguranca SAPGUI";
5. O robo clica em "Permitir".

A janela "Importar file" e tratada por SAP GUI Scripting. Uma janela
nativa de selecao de arquivo e suportada como fallback por pywinauto.
A janela externa de seguranca tambem e tratada por pywinauto.

Requer no Windows:
    pip install pywinauto pywin32
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.erros import AnexoFalhouError

TITULO_RE = r"(?i)^(abrir|open|importar.|import.)$"
BOTAO_RE = r"(?i)^&?\s*(abrir|open|importar|import|ok)\s*$"
TITULO_SEGURANCA_RE = (
    r"(?i).*"
    r"(seguran[cç]a\s*sap\s*gui|seguran[cç]a\s*sapgui|"
    r"sap\s*gui\s*security|sapgui\s*security)"
    r".*"
)
BOTAO_PERMITIR_RE = r"(?i)^&?\s*(permitir|allow)\s*$"

SAP_JANELA_IMPORTAR = "wnd[1]"
SAP_CAMPO_DIRETORIO = "wnd[1]/usr/ctxtDY_PATH"
SAP_CAMPO_ARQUIVO = "wnd[1]/usr/ctxtDY_FILENAME"
SAP_BOTAO_CONFIRMAR = "wnd[1]/tbar[0]/btn[0]"


def _eh_acesso_negado_com(exc: Exception) -> bool:
    """Retorna True quando o SAP negou temporariamente o acesso COM."""
    hresult = getattr(exc, "hresult", None)
    if hresult == -2147024891:
        return True
    texto = str(exc).casefold()
    return (
        "acesso negado" in texto
        or "access is denied" in texto
        or "-2147024891" in texto
    )


@dataclass(frozen=True)
class JanelaInfo:
    handle: int
    titulo: str
    classe: str
    botoes: tuple[str, ...] = ()


class AdaptadorSapGui:
    """Localiza e trata a janela SAP 'Importar file'."""

    def __init__(self) -> None:
        import win32com.client
        self._win32com = win32com.client

    def _aplicacao(self) -> Any:
        sap_gui = self._win32com.GetObject("SAPGUI")
        return sap_gui.GetScriptingEngine

    @staticmethod
    def _quantidade(colecao: Any) -> int:
        try:
            return int(colecao.Count)
        except Exception:
            return 0

    @staticmethod
    def _item(colecao: Any, indice: int) -> Any:
        try:
            return colecao.Item(indice)
        except Exception:
            return colecao(indice)

    @staticmethod
    def _obter_silencioso(sessao: Any, elemento_id: str) -> Any | None:
        try:
            return sessao.FindById(elemento_id)
        except Exception:
            return None

    def sessoes(self) -> list[Any]:
        aplicacao = self._aplicacao()
        encontradas: list[Any] = []

        for indice_conexao in range(self._quantidade(aplicacao.Children)):
            try:
                conexao = self._item(aplicacao.Children, indice_conexao)
            except Exception:
                continue

            for indice_sessao in range(self._quantidade(conexao.Children)):
                try:
                    sessao = self._item(conexao.Children, indice_sessao)
                except Exception:
                    continue
                encontradas.append(sessao)

        return encontradas

    def tratar_importar_file(self, caminho: Path) -> bool:
        """Preenche e confirma a janela SAP; False significa tentar novamente."""
        caminho = Path(caminho).expanduser().resolve()
        diretorio = str(caminho.parent)
        nome_arquivo = caminho.name

        try:
            sessoes = self.sessoes()
        except Exception as exc:
            if _eh_acesso_negado_com(exc):
                return False
            raise

        for sessao in sessoes:
            try:
                campo_diretorio = self._obter_silencioso(
                    sessao, SAP_CAMPO_DIRETORIO
                )
                campo_arquivo = self._obter_silencioso(
                    sessao, SAP_CAMPO_ARQUIVO
                )

                if campo_diretorio is None or campo_arquivo is None:
                    continue

                campo_diretorio.Text = diretorio
                campo_arquivo.Text = nome_arquivo
                time.sleep(0.2)

                botao = self._obter_silencioso(sessao, SAP_BOTAO_CONFIRMAR)
                if botao is not None:
                    botao.Press()
                    return True

                janela = self._obter_silencioso(sessao, SAP_JANELA_IMPORTAR)
                if janela is None:
                    continue

                janela.SendVKey(0)
                return True

            except Exception as exc:
                if _eh_acesso_negado_com(exc):
                    return False
                raise

        return False


class AdaptadorPywinauto:
    """Trata janelas nativas do Windows e a seguranca do SAP GUI."""

    def __init__(self) -> None:
        from pywinauto import Desktop
        self._desktop = Desktop

    def janelas(self) -> list[JanelaInfo]:
        achadas: list[JanelaInfo] = []
        desktop = self._desktop(backend="win32")

        for janela in desktop.windows(visible_only=True):
            try:
                classe = janela.class_name() or ""
                titulo = janela.window_text() or ""
                handle = janela.handle
            except Exception:
                continue

            try:
                botoes = tuple(
                    (controle.window_text() or "").strip()
                    for controle in janela.descendants(class_name="Button")
                )
            except Exception:
                botoes = ()

            achadas.append(JanelaInfo(handle, titulo, classe, botoes))

        return achadas

    def preencher_e_abrir(self, handle: int, caminho: Path) -> None:
        """Fallback para uma janela nativa de selecao de arquivo."""
        caminho = Path(caminho).expanduser().resolve()
        if not caminho.is_file():
            raise FileNotFoundError(f"Arquivo nao encontrado: {caminho}")

        dlg = self._desktop(backend="win32").window(handle=handle)
        dlg.wait("exists enabled visible ready", timeout=10, retry_interval=0.25)

        try:
            dlg.set_focus()
        except Exception:
            pass

        edit = self._localizar_campo_arquivo(dlg)
        edit.wait("exists enabled visible ready", timeout=10, retry_interval=0.25)

        try:
            edit.set_edit_text(str(caminho))
        except Exception:
            edit.set_text(str(caminho))

        time.sleep(0.3)
        botao = self._localizar_botao_principal(dlg)

        if botao is not None:
            try:
                botao.click()
            except Exception:
                botao.click_input()
        else:
            edit.type_keys("{ENTER}", set_foreground=True)

        try:
            dlg.wait_not("visible", timeout=10, retry_interval=0.25)
        except Exception:
            edit.type_keys("{ENTER}", set_foreground=True)
            dlg.wait_not("visible", timeout=5, retry_interval=0.25)

    def _localizar_campo_arquivo(self, dlg: Any) -> Any:
        erros: list[str] = []

        tentativas = [
            lambda: dlg.child_window(class_name="Edit", control_id=1148),
            lambda: dlg.child_window(
                class_name="ComboBoxEx32", found_index=0
            ).child_window(
                class_name="ComboBox", found_index=0
            ).child_window(
                class_name="Edit", found_index=0
            ),
            lambda: dlg.descendant_window(class_name="Edit", found_index=0),
        ]

        for localizar in tentativas:
            try:
                edit = localizar()
                edit.wait(
                    "exists enabled visible ready",
                    timeout=3,
                    retry_interval=0.25,
                )
                return edit
            except Exception as exc:
                erros.append(f"{type(exc).__name__}: {exc}")

        try:
            dlg_uia = self._desktop(backend="uia").window(handle=dlg.handle)
            dlg_uia.wait(
                "exists enabled visible ready",
                timeout=5,
                retry_interval=0.25,
            )

            try:
                edit = dlg_uia.child_window(
                    auto_id="1148", control_type="Edit"
                )
                edit.wait(
                    "exists enabled visible ready",
                    timeout=3,
                    retry_interval=0.25,
                )
                return edit
            except Exception:
                edit = dlg_uia.descendant_window(
                    control_type="Edit", found_index=0
                )
                edit.wait(
                    "exists enabled visible ready",
                    timeout=5,
                    retry_interval=0.25,
                )
                return edit
        except Exception as exc:
            erros.append(f"UIA {type(exc).__name__}: {exc}")

        raise RuntimeError(
            "Nao foi possivel localizar o campo da janela nativa. "
            + " | ".join(erros)
        )

    def _localizar_botao_principal(self, dlg: Any) -> Any | None:
        try:
            botao = dlg.child_window(class_name="Button", control_id=1)
            botao.wait(
                "exists enabled visible ready", timeout=3, retry_interval=0.25
            )
            return botao
        except Exception:
            pass

        try:
            botao = dlg.descendant_window(
                class_name="Button", title_re=BOTAO_RE
            )
            botao.wait(
                "exists enabled visible ready", timeout=3, retry_interval=0.25
            )
            return botao
        except Exception:
            pass

        try:
            dlg_uia = self._desktop(backend="uia").window(handle=dlg.handle)
            botao = dlg_uia.descendant_window(
                control_type="Button", title_re=BOTAO_RE
            )
            botao.wait(
                "exists enabled visible ready", timeout=3, retry_interval=0.25
            )
            return botao
        except Exception:
            return None

    def _janela_fechou(self, handle: int, timeout: float = 5.0) -> bool:
        fim = time.monotonic() + timeout

        while time.monotonic() < fim:
            try:
                janela = self._desktop(backend="win32").window(handle=handle)
                if not janela.exists(timeout=0.2) or not janela.is_visible():
                    return True
            except Exception:
                return True
            time.sleep(0.2)

        return False

    def clicar_botao(self, handle: int, botao_re: str) -> bool:
        """Clica em Permitir por Win32, UIA, Alt+P ou Shift+Tab+Enter."""
        try:
            dlg = self._desktop(backend="win32").window(handle=handle)
            dlg.wait("exists enabled visible ready", timeout=3, retry_interval=0.25)
            botao = dlg.descendant_window(
                class_name="Button", title_re=botao_re
            )
            botao.wait(
                "exists enabled visible ready", timeout=3, retry_interval=0.25
            )
            try:
                botao.click()
            except Exception:
                botao.click_input()
            if self._janela_fechou(handle):
                return True
        except Exception:
            pass

        try:
            dlg = self._desktop(backend="uia").window(handle=handle)
            dlg.wait("exists enabled visible ready", timeout=3, retry_interval=0.25)
            botao = dlg.descendant_window(
                control_type="Button", title_re=botao_re
            )
            botao.wait(
                "exists enabled visible ready", timeout=3, retry_interval=0.25
            )
            botao.click_input()
            if self._janela_fechou(handle):
                return True
        except Exception:
            pass

        try:
            from pywinauto.keyboard import send_keys
            dlg = self._desktop(backend="win32").window(handle=handle)
            dlg.set_focus()
            time.sleep(0.2)
            send_keys("%p", pause=0.1, with_spaces=True)
            if self._janela_fechou(handle):
                return True
        except Exception:
            pass

        try:
            from pywinauto.keyboard import send_keys
            dlg = self._desktop(backend="win32").window(handle=handle)
            dlg.set_focus()
            time.sleep(0.2)
            send_keys("+{TAB}{ENTER}", pause=0.15)
            return self._janela_fechou(handle)
        except Exception:
            return False


class TarefaDialogo:
    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.erro: str | None = None
        self.concluida = False
        self.seguranca_tratada = False
        self.seguranca_vista = False
        self.vigia: threading.Thread | None = None
        self._lock_seguranca = threading.Lock()
        self._clicadas: set[int] = set()
        self._parar = threading.Event()

    def cancelar(self) -> None:
        self._parar.set()

    def aguardar(self, timeout: float = 10) -> None:
        if self.thread is not None:
            self.thread.join(timeout)

        if self.thread is not None and self.thread.is_alive():
            self._parar.set()
            self.thread.join(timeout=1.0)
            raise AnexoFalhouError(
                "As janelas do anexo nao foram tratadas em "
                f"{timeout} segundos."
            )

        if self.erro:
            raise AnexoFalhouError(self.erro)

        if not self.concluida:
            raise AnexoFalhouError(
                "A rotina de janelas terminou sem confirmar o anexo."
            )


class DialogoArquivo:
    def __init__(
        self,
        timeout: int = 40,
        titulo_re: str = TITULO_RE,
        espera_seguranca: float = 8.0,
        adaptador: Any | None = None,
        adaptador_sap: Any | None = None,
        titulo_seguranca_re: str = TITULO_SEGURANCA_RE,
        botao_permitir_re: str = BOTAO_PERMITIR_RE,
        intervalo: float = 0.5,
        max_tentativas_seguranca: int = 3,
        log: Any | None = None,
    ) -> None:
        self.timeout = timeout
        self.titulo_re = titulo_re
        self.espera_seguranca = espera_seguranca
        self.titulo_seguranca_re = titulo_seguranca_re
        self.botao_permitir_re = botao_permitir_re
        self.intervalo = intervalo
        self.max_tentativas_seguranca = max_tentativas_seguranca
        self.log = log
        self._adaptador = adaptador
        self._adaptador_sap = adaptador_sap
        self._seguranca_vista: bool | None = None

    def _espera_atual(self) -> float:
        if self._seguranca_vista in (None, True):
            return self.espera_seguranca
        return min(self.espera_seguranca, 1.0)

    def iniciar(self, caminho: Path) -> TarefaDialogo:
        tarefa = TarefaDialogo()
        tarefa.thread = threading.Thread(
            target=self._rodar,
            args=(Path(caminho), tarefa),
            name="dialogo-arquivo-sap",
            daemon=True,
        )
        tarefa.thread.start()

        # Vigia do aviso "Seguranca SAPGUI" em thread PROPRIA (ver _vigiar_seguranca).
        tarefa.vigia = threading.Thread(
            target=self._vigiar_seguranca,
            args=(tarefa,),
            name="dialogo-vigia-seguranca",
            daemon=True,
        )
        tarefa.vigia.start()
        return tarefa

    def _clicar_permitir(
        self, adaptador: Any, janela: JanelaInfo, tarefa: TarefaDialogo
    ) -> bool:
        """Clica em 'Permitir' uma unica vez por janela, mesmo com duas threads tentando."""
        with tarefa._lock_seguranca:
            if janela.handle in tarefa._clicadas:
                return True

            tarefa.seguranca_vista = True
            if adaptador.clicar_botao(janela.handle, self.botao_permitir_re):
                tarefa._clicadas.add(janela.handle)
                tarefa.seguranca_tratada = True
                return True

            return False

    def _registrar_diagnostico(self, adaptador: Any, motivo: str) -> None:
        """Escreve no log quais janelas de dialogo estavam visiveis (para ajustar as expressoes)."""
        if self.log is None:
            return

        try:
            dialogos = [
                f"classe={j.classe!r} titulo={j.titulo!r} botoes={list(j.botoes)}"
                for j in adaptador.janelas()
                if j.classe == "#32770" or j.botoes
            ]
        except Exception as exc:
            dialogos = [f"(nao consegui listar: {type(exc).__name__}: {exc})"]

        self.log.warning(
            "%s. Janelas de dialogo visiveis agora: %s",
            motivo,
            " | ".join(dialogos) or "(nenhuma)",
        )

    def _vigiar_seguranca(self, tarefa: TarefaDialogo) -> None:
        """Clica em 'Permitir' em paralelo, sem depender da thread que preenche o SAP.

        Ao confirmar o "Importar file", o SAP GUI mostra o aviso de seguranca e a chamada de
        scripting (Press) FICA BLOQUEADA ate alguem clicar em Permitir. Se o clique dependesse
        da mesma thread, o robo esperaria para sempre e a pessoa teria que clicar a mao.
        """
        pythoncom = None
        com_inicializado = False

        try:
            try:
                import pythoncom
                pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
                com_inicializado = True
            except Exception:
                pass  # so o backend UIA precisa de COM; o win32 funciona sem

            try:
                adaptador = self._adaptador or AdaptadorPywinauto()
            except Exception:
                return  # sem pywinauto: a thread principal ja informa a dependencia ausente

            re_seguranca = re.compile(self.titulo_seguranca_re)
            re_permitir = re.compile(self.botao_permitir_re)

            inicio = time.monotonic()
            limite = inicio + max(self.timeout, 1) + self.espera_seguranca + 30
            fim_principal: float | None = None
            diagnostico_feito = False

            while time.monotonic() < limite and not tarefa._parar.is_set():
                if tarefa.thread is not None and not tarefa.thread.is_alive():
                    # a thread principal terminou: so uma pequena folga para um aviso tardio
                    fim_principal = fim_principal or time.monotonic()
                    if time.monotonic() - fim_principal > 1.5:
                        break

                try:
                    for janela in adaptador.janelas():
                        eh_seguranca = bool(
                            re_seguranca.search(janela.titulo)
                            or any(re_permitir.match(b) for b in janela.botoes)
                        )
                        if eh_seguranca and not self._clicar_permitir(
                            adaptador, janela, tarefa
                        ) and not diagnostico_feito:
                            diagnostico_feito = True
                            self._registrar_diagnostico(
                                adaptador,
                                "O aviso de seguranca apareceu, mas o clique em "
                                "'Permitir' falhou",
                            )
                except Exception:
                    pass  # uma varredura ruim nao pode derrubar a vigia

                if (
                    not diagnostico_feito
                    and not tarefa.seguranca_tratada
                    and time.monotonic() - inicio > 10
                ):
                    diagnostico_feito = True
                    self._registrar_diagnostico(
                        adaptador,
                        "Anexo aguardando ha 10s sem tratar o aviso de seguranca",
                    )

                time.sleep(min(self.intervalo, 0.3))
        finally:
            if pythoncom is not None and com_inicializado:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _rodar(self, caminho: Path, tarefa: TarefaDialogo) -> None:
        caminho = Path(caminho).expanduser().resolve()

        if not caminho.is_file():
            tarefa.erro = f"Arquivo nao encontrado para anexar: {caminho}"
            return

        try:
            with caminho.open("rb") as arquivo:
                arquivo.read(1)
        except OSError as exc:
            tarefa.erro = (
                "O arquivo existe, mas nao esta disponivel para leitura: "
                f"{caminho}. Erro: {type(exc).__name__}: {exc}"
            )
            return

        pythoncom = None
        com_inicializado = False

        try:
            import pythoncom
            try:
                pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
                com_inicializado = True
            except Exception as exc:
                if getattr(exc, "hresult", None) != -2147417850:
                    tarefa.erro = (
                        "Nao foi possivel inicializar COM em modo STA: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    return

            adaptador = self._adaptador or AdaptadorPywinauto()
            adaptador_sap = self._adaptador_sap or AdaptadorSapGui()

            re_arquivo = re.compile(self.titulo_re)
            re_abrir = re.compile(BOTAO_RE)
            re_seguranca = re.compile(self.titulo_seguranca_re)
            re_permitir = re.compile(self.botao_permitir_re)

            fim = time.monotonic() + self.timeout
            arquivo_ok = False
            seguranca_ok = False
            seguranca_vista = False
            limite_seguranca: float | None = None
            tentativas_seguranca = 0

            while time.monotonic() < fim:
                if tarefa._parar.is_set():
                    return

                if tarefa.seguranca_tratada:  # a vigia ja clicou em Permitir
                    seguranca_ok = True
                    seguranca_vista = True

                if not arquivo_ok:
                    try:
                        arquivo_ok = adaptador_sap.tratar_importar_file(caminho)
                    except Exception as exc:
                        if not _eh_acesso_negado_com(exc):
                            tarefa.erro = (
                                "Falha ao preencher a janela SAP 'Importar file': "
                                f"{type(exc).__name__}: {exc}"
                            )
                            return

                    if arquivo_ok:
                        limite_seguranca = (
                            time.monotonic() + self._espera_atual()
                        )

                for janela in adaptador.janelas():
                    if tarefa._parar.is_set():
                        return

                    tem_permitir = any(
                        re_permitir.match(botao) for botao in janela.botoes
                    )
                    eh_seguranca = bool(
                        re_seguranca.search(janela.titulo) or tem_permitir
                    )

                    if not seguranca_ok and eh_seguranca:
                        seguranca_vista = True

                        if tentativas_seguranca >= self.max_tentativas_seguranca:
                            tarefa.erro = (
                                "A janela 'Seguranca SAPGUI' apareceu, mas "
                                "Permitir nao foi acionado apos "
                                f"{self.max_tentativas_seguranca} tentativas."
                            )
                            return

                        tentativas_seguranca += 1
                        seguranca_ok = self._clicar_permitir(
                            adaptador, janela, tarefa
                        )
                        if not seguranca_ok:
                            time.sleep(0.5)
                            continue

                    tem_abrir = any(
                        re_abrir.match(botao) for botao in janela.botoes
                    )
                    eh_arquivo_nativo = bool(
                        not eh_seguranca
                        and janela.classe == "#32770"
                        and (tem_abrir or re_arquivo.match(janela.titulo))
                    )

                    if not arquivo_ok and eh_arquivo_nativo:
                        adaptador.preencher_e_abrir(janela.handle, caminho)
                        arquivo_ok = True
                        limite_seguranca = (
                            time.monotonic() + self._espera_atual()
                        )

                if arquivo_ok:
                    prazo_encerrado = bool(
                        limite_seguranca is not None
                        and time.monotonic() >= limite_seguranca
                    )
                    if seguranca_ok or prazo_encerrado:
                        break

                time.sleep(self.intervalo)

            seguranca_ok = seguranca_ok or tarefa.seguranca_tratada
            seguranca_vista = seguranca_vista or seguranca_ok
            tarefa.seguranca_tratada = seguranca_ok

            if seguranca_vista and not seguranca_ok:
                tarefa.erro = (
                    "A janela 'Seguranca SAPGUI' apareceu, mas nao foi "
                    "possivel clicar em 'Permitir'."
                )
                return

            if not arquivo_ok:
                tarefa.erro = (
                    "A janela de arquivo nao foi tratada em "
                    f"{self.timeout} segundos. Arquivo: {caminho}"
                )
                return

            self._seguranca_vista = seguranca_vista
            tarefa.concluida = True

        except ImportError as exc:
            tarefa.erro = (
                "Dependencia ausente. Execute: pip install pywinauto pywin32. "
                f"Erro: {exc}"
            )
        except Exception as exc:
            tarefa.erro = (
                "Falha ao tratar as janelas do anexo: "
                f"{type(exc).__name__}: {exc}"
            )
        finally:
            if pythoncom is not None and com_inicializado:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass