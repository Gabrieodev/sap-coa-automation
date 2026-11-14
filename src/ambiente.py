"""Resolve onde estão, neste computador, a base de controle e as pastas de documentos REAIS.

O robô roda por padrão contra o SharePoint real (via pasta sincronizada do OneDrive). Se não
achar a base ou a pasta de documentos, ele PARA com uma mensagem clara — nunca cai em dados de
demonstração (esses só existem com `main.py --simulado`).
"""
from __future__ import annotations

from pathlib import Path

from src.arquivos import sharepoint_local as sp
from src.erros import ErroFatal

_AJUDA = ("\nDica: rode `python scripts\\localizar_pastas_sharepoint.py` para ver o que o OneDrive "
          "deste computador está sincronizando e quais valores usar.")


def resolver_planilha(cfg) -> Path:
    """Arquivo .xlsx da base de controle: COA_PLANILHA (arquivo ou pasta) ou a pasta do link."""
    alvo = cfg.planilha
    if alvo is None:
        try:
            pasta = sp.resolver_pasta_local(cfg.url_base_controle)
        except ValueError as e:
            raise ErroFatal(f"url_base_controle inválida: {e}") from e
        if pasta is None:
            raise ErroFatal(
                "Não encontrei no computador a pasta sincronizada da base de controle "
                f"({cfg.url_base_controle}). Abra a pasta 'Controle robô COA' no SharePoint e use "
                "'Sincronizar' (ou 'Adicionar atalho ao OneDrive'), ou informe COA_PLANILHA." + _AJUDA)
        alvo = pasta
    alvo = Path(alvo)
    if alvo.is_dir():
        arquivo = sp.base_mais_recente(alvo, cfg.padrao_base_controle)
        if arquivo is None:
            raise ErroFatal(f"Nenhum arquivo '{cfg.padrao_base_controle}' na pasta {alvo}")
        return arquivo
    if not alvo.is_file():
        raise ErroFatal(f"Base de controle não encontrada: {alvo}")
    return alvo


def resolver_raiz_arquivos(cfg) -> Path:
    """Pasta que contém as pastas de processo (a de 'DOCS PROCESSOS IMPORTAÇÃO')."""
    if cfg.raiz_arquivos is not None:
        raiz = Path(cfg.raiz_arquivos)
    else:
        raiz = None
        if cfg.url_pasta_processos:  # 1) pelo link do SharePoint
            try:
                raiz = sp.resolver_pasta_local(cfg.url_pasta_processos)
            except ValueError as e:
                raise ErroFatal(f"url_pasta_processos inválida: {e}") from e
        if raiz is None:  # 2) pelo nome da pasta, em tudo que o OneDrive sincroniza (inclui atalhos,
            # cuja biblioteca no disco tem outro nome, ex.: 'ICL BR Comex Team - KPI MENSAL')
            try:
                site = sp.interpretar_link(cfg.url_base_controle).site
            except ValueError:
                site = ""
            raizes = sp.raizes_onedrive()
            buscar_em = list(dict.fromkeys((sp.bibliotecas_locais(site, raizes) if site else []) + raizes))
            raiz = sp.localizar_pasta_por_nome(cfg.nome_pasta_processos, buscar_em)
        if raiz is None:
            raise ErroFatal(
                f"Não encontrei a pasta '{cfg.nome_pasta_processos}' no que o OneDrive sincroniza. "
                "Sincronize-a (ou adicione atalho ao OneDrive) ou informe COA_RAIZ_ARQUIVOS." + _AJUDA)
    # Pasta informada à mão (COA_RAIZ_ARQUIVOS) não é exigida na partida: sem pendências o robô nem
    # precisa dela, e se faltar quando precisar, cada item acusa "pasta raiz inacessível".
    return raiz
