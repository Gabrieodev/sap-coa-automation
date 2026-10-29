from src.sap.exceptions import SapNaoAbertoError, SapNaoLogadoError


class SapConnection:

    @staticmethod
    def get_application():
        try:
            import win32com.client  # import tardio: permite rodar testes/simulação sem SAP
            sap_gui = win32com.client.GetObject("SAPGUI")
            return sap_gui.GetScriptingEngine
        except Exception as e:
            raise SapNaoAbertoError("SAP GUI não está aberto.") from e

    @staticmethod
    def get_connection(index=0):
        app = SapConnection.get_application()

        if app.Children.Count == 0:
            raise SapNaoLogadoError(
                "SAP GUI aberto, porém nenhum ambiente está logado."
            )

        return app.Children(index)
