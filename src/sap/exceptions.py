from src.erros import ErroDeItem, ErroFatal


# ---- Fatais: sem SAP utilizável não adianta seguir para o próximo pedido ----
class SapNaoAbertoError(ErroFatal):
    pass


class SapNaoLogadoError(ErroFatal):
    pass


class SessaoSapPerdidaError(ErroFatal):
    """A sessão deixou de responder (fechada, travada ou conexão perdida)."""


# ---- Por item: o pedido tem problema, o SAP segue saudável ----
class PedidoNaoEncontradoError(ErroDeItem):
    pass


class PedidoBloqueadoError(ErroDeItem):
    pass


class SemAutorizacaoError(ErroDeItem):
    pass


class PedidoComErroError(ErroDeItem):
    """Mensagem de erro do SAP que não caiu em nenhuma categoria acima."""


class ElementoSapNaoEncontradoError(ErroDeItem):
    """findById falhou: seletor desatualizado ou tela diferente da esperada."""
    tecnico = True
