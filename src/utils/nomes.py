from pathlib import Path


def chave_anexo(nome: str) -> str:
    """Chave para comparar arquivo local x título do anexo no SAP.

    O SAP costuma exibir o título sem a extensão e pode alterar caixa/espaços, então
    comparamos só o nome-base em minúsculas.
    """
    return Path(str(nome).strip()).stem.casefold()
