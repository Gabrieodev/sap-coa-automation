"""Teclado do Windows para o robô (pywinauto). Só existe no Windows; usado como último recurso
quando o scripting do SAP não consegue acionar um item de menu."""


def enviar(teclas: str) -> None:
    try:
        from pywinauto.keyboard import send_keys
    except ImportError as e:
        raise RuntimeError("pywinauto não instalado (pip install pywinauto)") from e
    send_keys(teclas)


def esc() -> None:
    """Fecha um menu de contexto que ficou aberto depois de uma tentativa que falhou."""
    enviar("{ESC}")
