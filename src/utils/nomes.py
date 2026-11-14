"""Convenções de nome: processo (base) -> pasta (SharePoint), e arquivo local -> anexo (SAP)."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path

from src.erros import AnexoAmbiguoError


def nome_pasta_processo(processo: str) -> str:
    """Nome que o processo tem como pasta no SharePoint.

    Na base o processo é '0226/25'; o SharePoint não aceita '/' em nome de pasta, então a
    pasta é '0226-25'. ('\\\\' recebe o mesmo tratamento; espaços nas pontas são removidos.)
    """
    return re.sub(r"\s*[/\\]\s*", "-", re.sub(r"\s+", " ", str(processo).strip()))


def nomes_pasta_candidatos(processo: str) -> list[str]:
    """Nomes exatos que a pasta do processo pode ter: separador '-' (padrão) ou '_'.

    '0226/25' -> ['0226-25', '0226_25']. Pastas com sufixo ('0002-23 (ANTIGO ...)') e outras
    variações de caixa/espaço são achadas depois, pela busca por prefixo do provedor.
    """
    com_hifen = nome_pasta_processo(processo)
    com_underline = re.sub(r"\s*[/\\]\s*", "_", re.sub(r"\s+", " ", str(processo).strip()))
    return list(dict.fromkeys(n for n in (com_hifen, com_underline) if n))


def chave_anexo(nome: str) -> str:
    """Chave para comparar arquivo local x título do anexo no SAP.

    O SAP costuma exibir o título sem a extensão e pode alterar caixa/espaços, então
    comparamos só o nome-base em minúsculas.
    """
    return Path(str(nome).strip()).stem.casefold()


def anexos_pendentes(arquivos: list[Path], titulos_sap: list[str]) -> list[Path]:
    """Dos `arquivos` da pasta, devolve os que ainda NÃO estão anexados no pedido.

    Como a pasta agora vai inteira (PDF, Excel, Word...), dois arquivos podem ter o mesmo nome-base
    ('COA.pdf' e 'COA.xlsx'). O SAP pode mostrar só o nome-base, então:
      * nome completo igual a um título do SAP -> já anexado;
      * nome-base único na pasta e igual a um título -> já anexado;
      * nome-base repetido na pasta: sobram os arquivos sem título com nome completo; conta os
        títulos "só nome-base" do SAP. Cobrem todos -> já anexados; nenhum -> todos pendentes;
        só parte -> AnexoAmbiguoError (não dá para saber qual falta: melhor um humano olhar do
        que duplicar ou deixar de anexar).
    """
    completos = {str(t).strip().casefold() for t in titulos_sap}
    por_base = Counter(chave_anexo(t) for t in titulos_sap)
    so_base = Counter(chave_anexo(t) for t in titulos_sap
                      if str(t).strip().casefold() == chave_anexo(t))  # título sem extensão
    usam_base = Counter(chave_anexo(a.name) for a in arquivos)

    pendentes: list[Path] = []
    restantes: dict[str, list[Path]] = {}
    for a in arquivos:
        base = chave_anexo(a.name)
        if a.name.strip().casefold() in completos:
            continue
        if usam_base[base] == 1:
            if por_base[base] == 0:
                pendentes.append(a)
            continue
        restantes.setdefault(base, []).append(a)

    for base, grupo in restantes.items():
        presentes = so_base[base]
        if presentes == 0:
            pendentes.extend(grupo)
        elif presentes < len(grupo):
            raise AnexoAmbiguoError(
                f"{usam_base[base]} arquivos da pasta compartilham o nome '{base}' "
                f"({[g.name for g in grupo]} sem anexo identificável) e o pedido tem só "
                f"{presentes} título(s) '{base}' sem extensão; não sei qual falta — "
                f"conferir manualmente")
    return sorted(pendentes, key=lambda p: p.name)


VAZIO = "<VAZIO>"  # como escrever "célula em branco" em filtro_processar / filtro_ignorar


def normalizar_valor(texto: str) -> str:
    """Compara valores de coluna sem caixa, acento nem espaços repetidos. Vazio -> '<VAZIO>'."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\s+", " ", t).strip().upper()
    return t or VAZIO
