# Navegação dentro do SAP
import time

from src.sap.exceptions import SessaoSapPerdidaError
from src.sap.sessao import SapSession


class SapNavigation:

    def __init__(self, session=None):
        self.session = session or SapSession.get()

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
