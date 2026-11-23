"""Do link do SharePoint para a pasta sincronizada no computador (OneDrive).

O robô não baixa nada pela internet: lê e grava nas pastas que o OneDrive sincroniza. Este módulo
descobre, a partir do LINK do SharePoint, qual é a pasta correspondente no disco, e escolhe a base
de controle mais recente (o Power BI gera um arquivo novo a cada exportação:
'DATA BASE - 2026-11-11T152807.964.xlsx').

Tudo aqui é função simples e recebe as "raízes do OneDrive" como parâmetro, para poder ser testado
sem OneDrive de verdade.
"""
from __future__ import annotations

import fnmatch
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# bibliotecas aparecem como "Shared Documents" na URL e "<Site> - Documents" (ou "Documentos") no disco
_PALAVRA_BIBLIOTECA = "document"


@dataclass(frozen=True)
class LinkSharePoint:
    site: str                  # 'ICLBRComexTeam'
    biblioteca: str            # 'Shared Documents'
    caminho: tuple[str, ...]   # ('IMPO-ADS', 'Controle robô COA', 'DATA BASE - ....xlsx')

    @property
    def e_arquivo(self) -> bool:
        return bool(self.caminho) and bool(Path(self.caminho[-1]).suffix)

    @property
    def pasta(self) -> tuple[str, ...]:
        """Caminho da pasta (se o link for de um arquivo, a pasta que o contém)."""
        return self.caminho[:-1] if self.e_arquivo else self.caminho


def _norm(texto: str) -> str:
    """Minúsculas, sem acento e só letras/números: 'ICL BR Comex Team - Documents' -> 'iclbr...'."""
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", t.casefold())


def interpretar_link(url: str) -> LinkSharePoint:
    """Aceita link de arquivo/pasta do SharePoint em qualquer um destes formatos:
      https://x.sharepoint.com/:x:/r/sites/SITE/Shared%20Documents/pasta/arq.xlsx?d=...   (compartilhar)
      https://x.sharepoint.com/sites/SITE/Shared%20Documents/pasta/arq.xlsx                (direto)
      https://x.sharepoint.com/sites/SITE/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2F...
    """
    partes = urlparse(url.strip())
    caminho = unquote(partes.path)
    id_param = parse_qs(partes.query).get("id")
    if id_param:  # visão de pasta: o caminho verdadeiro vem em ?id=/sites/SITE/Biblioteca/pasta
        caminho = unquote(id_param[0])
    segs = [s for s in caminho.split("/") if s]
    for marca in ("sites", "teams"):
        if marca in segs:
            i = segs.index(marca)
            break
    else:
        raise ValueError(f"Link não parece ser de um site do SharePoint (faltou /sites/): {url}")
    if len(segs) < i + 3:
        raise ValueError(f"Link sem biblioteca/pasta depois do site: {url}")
    site, biblioteca, resto = segs[i + 1], segs[i + 2], segs[i + 3:]
    resto = [s for s in resto if s.lower() not in ("forms", "allitems.aspx")]
    return LinkSharePoint(site=site, biblioteca=biblioteca, caminho=tuple(resto))


# ------------------------------------------------------------------ raízes do OneDrive
def raizes_onedrive(env: dict | None = None, home: Path | None = None) -> list[Path]:
    """Pastas-raiz do OneDrive corporativo neste computador (as que existem)."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    cand: list[Path] = []
    for var in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
        if env.get(var):
            cand.append(Path(env[var]))
    try:
        # 'C:\Users\voce\ICL Group' (bibliotecas do SharePoint) e 'OneDrive - ICL Group' (atalhos)
        cand += [p for p in sorted(home.iterdir())
                 if p.is_dir() and (p.name.lower().startswith("onedrive") or "icl" in p.name.lower())]
    except OSError:
        pass
    unicos: list[Path] = []
    for p in cand:
        if p.is_dir() and p not in unicos:
            unicos.append(p)
    return unicos


def _subpastas(p: Path) -> list[Path]:
    try:
        with os.scandir(p) as it:
            return sorted(Path(e.path) for e in it if e.is_dir())
    except OSError:
        return []


def bibliotecas_locais(site: str, raizes: list[Path] | None = None) -> list[Path]:
    """Pastas do disco que espelham a biblioteca do site (ex.: '...\\ICL Group\\ICL BR Comex Team - Documents').

    Casa pelo nome do site sem espaços/acentos ('ICLBRComexTeam' ~ 'ICL BR Comex Team'). Se houver
    mais de uma (ex.: 'Documents' e 'Site Assets'), as de 'Documents/Documentos' vêm primeiro.
    """
    raizes = raizes_onedrive() if raizes is None else raizes
    alvo = _norm(site)
    achadas: list[Path] = []
    for raiz in raizes:
        if alvo in _norm(raiz.name):
            achadas.append(raiz)
        achadas += [p for p in _subpastas(raiz) if alvo in _norm(p.name)]
    unicas = list(dict.fromkeys(achadas))
    return sorted(unicas, key=lambda p: _PALAVRA_BIBLIOTECA not in _norm(p.name))


def resolver_pasta_local(url: str, raizes: list[Path] | None = None) -> Path | None:
    """Pasta local correspondente ao link (se o link for de arquivo, a pasta que o contém)."""
    link = interpretar_link(url)
    for biblio in bibliotecas_locais(link.site, raizes):
        p = biblio.joinpath(*link.pasta)
        if p.is_dir():
            return p
    return None


def localizar_pasta_por_nome(nome: str, bibliotecas: list[Path], profundidade: int = 3) -> Path | None:
    """Procura uma pasta pelo nome (sem caixa/acento) até `profundidade` níveis dentro das
    bibliotecas. Não desce dentro da pasta encontrada (portanto nunca varre as pastas de processo)."""
    alvo = _norm(nome)
    for biblio in bibliotecas:
        nivel = [biblio]
        for _ in range(profundidade):
            proximo: list[Path] = []
            for pasta in nivel:
                for sub in _subpastas(pasta):
                    if _norm(sub.name) == alvo:
                        return sub
                    proximo.append(sub)
            nivel = proximo
    return None


# ------------------------------------------------------------------ base de controle
_TS = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{6})")


def base_mais_recente(pasta: Path, padrao: str = "DATA BASE*.xlsx") -> Path | None:
    """A base de controle mais nova da pasta: pelo carimbo no nome (2026-11-11T152807) e, se não
    houver, pela data de modificação. Ignora temporários do Excel ('~$...')."""
    try:
        arquivos = [f for f in pasta.iterdir()
                    if f.is_file() and not f.name.startswith("~$")
                    and fnmatch.fnmatch(f.name.lower(), padrao.lower())]
    except OSError:
        return None

    def chave(f: Path):
        m = _TS.search(f.name)
        return (m.group(1) if m else "", f.stat().st_mtime)

    return max(arquivos, key=chave) if arquivos else None
