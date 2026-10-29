# Mantem a sessão dentro do SAP

from src.sap.conexao import SapConnection

class SapSession:

    @staticmethod
    def get(index_conexao=0, index_sessao=0):
        connection = SapConnection.get_connection(index_conexao)
        return connection.Children(index_sessao)