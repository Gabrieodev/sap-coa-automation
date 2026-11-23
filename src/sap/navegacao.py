# Navegação dentro do SAP
import time

from src.sap.exceptions import ElementoSapNaoEncontradoError, SessaoSapPerdidaError
from src.sap.sessao import SapSession


class _FalhaAlternativa(Exception):
    """Uma alternativa de menu não pôde ser tentada (ex.: teclado indisponível)."""


class SapNavigation:

    def __init__(self, session=None, fechar_menu=None, enviar_teclas=None):
        self.session = session or SapSession.get()
        # Opcionais (o main injeta as versões reais, via pywinauto; nos testes ficam desligadas para
        # nunca mandar tecla para a área de trabalho de quem roda a suíte):
        self._fechar_menu = fechar_menu      # callable(): fecha menu de contexto que ficou aberto
        self._enviar_teclas = enviar_teclas  # callable(str): digita no Windows (ex.: "c{ENTER}")

    # ---- originais ----
    def abrir_transacao(self, codigo):
        self.session.StartTransaction(codigo)

    def enter(self):
        self.session.sendVKey(0)

    def voltar(self):
        self.session.sendVKey(3)

    def sair(self):
        self.session.sendVKey(15)

    def cancelar(self):
        self.session.sendVKey(12)

    # ---- novos ----
    def aguardar(self, timeout=30):
        """Espera o SAP terminar o processamento (session.Busy)."""
        fim = time.monotonic() + timeout
        while self.session.Busy:
            if time.monotonic() > fim:
                raise SessaoSapPerdidaError(f"SAP continuou ocupado por mais de {timeout}s")
            time.sleep(0.2)

    def obter(self, id_):
        return self.session.findById(id_)

    def existe(self, id_) -> bool:
        try:
            self.session.findById(id_)
            return True
        except Exception:
            return False

    def _fechar_menu_aberto(self) -> None:
        if self._fechar_menu:
            try:
                self._fechar_menu()
                time.sleep(0.3)
            except Exception:
                pass

    def achar_grid(self, id_raiz: str, max_nivel: int = 6):
        """Primeira tabela (GuiGridView) dentro de `id_raiz`, em largura; None se não houver.
        Usado quando o ID exato da tabela não é conhecido."""
        try:
            raiz = self.session.findById(id_raiz)
        except Exception:
            return None
        fila = [(raiz, 0)]
        while fila:
            el, nivel = fila.pop(0)
            if str(getattr(el, "SubType", "")) == "GridView":
                return el
            if nivel >= max_nivel:
                continue
            try:
                filhos = el.Children
                for i in range(int(filhos.Count)):
                    fila.append((filhos.ElementAt(i), nivel + 1))
            except Exception:
                continue
        return None

    def sessao_viva(self) -> bool:
        try:
            self.session.Info.SystemName
            return True
        except Exception:
            return False

    def transacao_atual(self) -> str:
        return str(self.session.Info.Transaction)

    def status_barra(self) -> tuple[str, str]:
        """(tipo, texto) da barra de status. Tipos: S sucesso, W aviso, E erro, A abort, I info."""
        sbar = self.session.findById("wnd[0]/sbar")
        return str(sbar.MessageType or ""), str(sbar.Text or "")

    def popups_abertos(self) -> int:
        """Janelas modais abertas (wnd[1], wnd[2], ...)."""
        return max(int(self.session.Children.Count) - 1, 0)

    def fechar_janela(self, n):
        self.session.findById(f"wnd[{n}]").close()

    def clicar_menu_contexto(self, id_barra, botao, item):
        barra = self.session.findById(id_barra)
        barra.pressContextButton(botao)
        barra.selectContextMenuItem(item)

    def clicar_menu_contexto_com_alternativas(self, id_barra, botao, itens) -> str:
        """Tenta cada item até um funcionar e devolve o que funcionou. Item que começa com '%' é
        código de função (selectContextMenuItem); os demais são o TEXTO exibido
        (selectContextMenuItemByText). Útil quando o código varia entre versões do SAP GUI."""
        barra = self.session.findById(id_barra)   # falha aqui = seletor da barra errado
        falhas: list[str] = []
        for item in itens:
            item = str(item)
            fase = "abrir o menu (pressContextButton)"
            try:
                barra.pressContextButton(botao)
                fase = "escolher o item"
                if item.startswith("%"):                       # código de função
                    barra.selectContextMenuItem(item)
                elif item.startswith("pos:"):                  # posição, ex.: "pos:0|0"
                    barra.selectContextMenuItemByPosition(item[4:])
                elif item.startswith("teclado:"):              # último recurso: digitar no menu aberto
                    if not self._enviar_teclas:
                        raise _FalhaAlternativa("teclado indisponível")
                    try:
                        self._enviar_teclas(item[len("teclado:"):])
                    except Exception as e:
                        raise _FalhaAlternativa(str(e)) from e
                else:                                          # texto exibido no menu
                    barra.selectContextMenuItemByText(item)
                return item
            except Exception as e:
                if type(e).__name__ != "com_error" and not isinstance(e, _FalhaAlternativa):
                    raise
                falhas.append(f"{item!r} falhou ao {fase}: {e}")
                self._fechar_menu_aberto()  # senão o menu aberto faz as próximas tentativas falharem à toa
        if not self.sessao_viva():
            raise SessaoSapPerdidaError("Sessão SAP não responde ao abrir o menu de Serviços para objeto")
        raise ElementoSapNaoEncontradoError(
            "Nenhuma das formas de acionar o item do menu funcionou -> " + " | ".join(falhas)
            + ". Grave o passo manual (Alt+F12 > Script Recording and Playback) e ajuste "
              "GOS_CRIAR_ANEXO_ALTERNATIVAS em src/sap/seletores.py")
