"""Origem dos arquivos do COA.

`ProvedorArquivos` é a interface; hoje existe uma implementação (pasta sincronizada
do OneDrive). Se um dia quiserem ler direto pela Microsoft Graph API, basta criar outra
classe com o mesmo método `obter_arquivos` — o resto do robô não muda.
"""
from __future__ import annotations

import os
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path

from src.erros import (ArquivoIndisponivelError, PastaProcessoAmbiguaError,
                       PastaProcessoNaoEncontradaError, SemArquivosError)
from src.utils.nomes import nome_pasta_processo, nomes_pasta_candidatos

_IGNORAR_NOMES = {"thumbs.db", "desktop.ini", ".ds_store"}

# Atributos do Windows que indicam arquivo "só na nuvem" (OneDrive Files On-Demand)
_ATRIB_NUVEM = 0x1000 | 0x40000 | 0x400000  # OFFLINE | RECALL_ON_OPEN | RECALL_ON_DATA_ACCESS


class ProvedorArquivos(ABC):
    @abstractmethod
    def obter_arquivos(self, processo: str) -> list[Path]:
        """Devolve os arquivos locais prontos para anexar, ou levanta ErroDeItem."""


def _chave(texto: str) -> str:
    """Normaliza para comparar nome de pasta x número do processo.

    A planilha traz '0226/25', mas o SharePoint não aceita '/' em nome de pasta, então a pasta é
    '0226-25'. Por isso '/', '\\', espaço e '_' viram '-'."""
    return re.sub(r"[\s_/\\]+", "-", texto.strip().lower())


class PastaSincronizada(ProvedorArquivos):
    """Lê as pastas de processo da biblioteca do SharePoint sincronizada pelo OneDrive.

    O robô só olha os processos que estão na base: para cada um, vai DIRETO na pasta
    `<raiz>/<processo com '/' trocado por '-'>`. O restante do SharePoint nunca é percorrido.
    A listagem de uma pasta inteira só acontece como plano B (pasta com sufixo no nome, ex.:
    '0002-23 (ANTIGO 1-9145)'), uma vez por pasta-base e apenas se algum processo não tiver
    pasta com o nome exato.
    """

    def __init__(self, raiz: Path, extensoes: tuple[str, ...] = (),
                 timeout_download: int = 60, log=None, profundidade: int = 1,
                 buscar_por_prefixo: bool = True):
        """extensoes: () = anexa tudo que estiver na pasta; ex.: ('.pdf',) restringe.
        profundidade=1: as pastas de processo ficam direto na raiz. 2: dentro de uma subpasta
        da raiz (ex.: por ano), e assim por diante.
        buscar_por_prefixo=False: só aceita pasta com nome exato (nunca lista a raiz)."""
        self.raiz = Path(raiz)
        self.profundidade = max(int(profundidade), 1)
        self.buscar_por_prefixo = buscar_por_prefixo
        self.extensoes = tuple(("." + e.lstrip(".")).lower() for e in extensoes if e.strip("."))
        self.timeout_download = timeout_download
        self.log = log
        self._bases_cache: list[Path] | None = None
        self._listagens: dict[Path, list[Path]] = {}
        self.listagens = 0          # quantas pastas foram listadas (métrica/teste: deve ser ~0)

    # ------------------------------------------------------------------ localizar
    def _listar_subpastas(self, base: Path) -> list[Path]:
        """Lista as subpastas de `base` (1 listagem por pasta, em cache)."""
        if base not in self._listagens:
            self.listagens += 1
            try:
                with os.scandir(base) as it:
                    self._listagens[base] = [Path(e.path) for e in it if e.is_dir()]
            except OSError:
                self._listagens[base] = []
        return self._listagens[base]

    def _bases(self) -> list[Path]:
        """Pastas que PODEM conter pastas de processo: a raiz e, se profundidade>1, as
        subpastas intermediárias (ex.: anos). Nunca desce até as pastas de processo."""
        if self._bases_cache is None:
            bases, nivel = [self.raiz], [self.raiz]
            for _ in range(self.profundidade - 1):
                nivel = [sub for b in nivel for sub in self._listar_subpastas(b)]
                bases.extend(nivel)
            self._bases_cache = bases
        return self._bases_cache

    def _rel(self, p: Path) -> str:
        return str(p.relative_to(self.raiz))

    def localizar_pasta(self, processo: str) -> Path:
        if not self.raiz.exists():
            raise PastaProcessoNaoEncontradaError(
                f"Pasta raiz de arquivos inacessível: {self.raiz} (OneDrive sincronizado?)")
        nome = nome_pasta_processo(processo)
        bases = self._bases()

        # 1) acesso direto ('0226-25' ou '0226_25'): uma checagem por base, sem listar nada
        exatas = [b / n for b in bases for n in nomes_pasta_candidatos(processo) if (b / n).is_dir()]
        if len(exatas) == 1:
            return exatas[0]
        if len(exatas) > 1:
            raise PastaProcessoAmbiguaError(
                f"{len(exatas)} pastas casam com '{processo}': {[self._rel(p) for p in exatas]}")

        # 2) plano B: pasta com sufixo / caixa diferente. Só aqui há listagem.
        if self.buscar_por_prefixo:
            alvo = _chave(processo)
            # "PROC-2026-0008 - Fornecedor X": o nome começa com o número do processo, seguido
            # de separador (evita 'PROC-1' casar com 'PROC-10')
            padrao = re.compile(rf"^{re.escape(alvo)}(?![0-9a-z])")
            todas = [p for b in bases for p in self._listar_subpastas(b)]
            iguais = [p for p in todas if _chave(p.name) == alvo]
            candidatas = iguais or [p for p in todas if padrao.match(_chave(p.name))]
            if len(candidatas) == 1:
                return candidatas[0]
            if len(candidatas) > 1:
                raise PastaProcessoAmbiguaError(
                    f"{len(candidatas)} pastas casam com '{processo}': "
                    f"{[self._rel(p) for p in candidatas]}")
        raise PastaProcessoNaoEncontradaError(
            f"Nenhuma pasta para o processo '{processo}' (procurei '{nome}')")

    # ------------------------------------------------------------------ arquivos
    def _elegivel(self, f: Path) -> bool:
        nome = f.name.lower()
        if nome.startswith("~$") or nome.startswith(".") or nome in _IGNORAR_NOMES:
            return False  # lixo do sistema/Office: nunca é conteúdo do processo
        if nome.endswith((".tmp", ".crdownload", ".partial")):
            return False
        return not self.extensoes or f.suffix.lower() in self.extensoes

    def obter_arquivos(self, processo: str) -> list[Path]:
        """Todos os arquivos da pasta do processo (não só o COA), exceto lixo/temporários."""
        pasta = self.localizar_pasta(processo)
        entradas = sorted(pasta.iterdir())
        subpastas = [e.name for e in entradas if e.is_dir()]
        if subpastas and self.log:
            self.log.warning("  pasta '%s' tem subpastas que NÃO serão anexadas: %s",
                             pasta.name, subpastas)
        elegiveis = [f for f in entradas if f.is_file() and self._elegivel(f)]
        if not elegiveis:
            filtro = f" {self.extensoes}" if self.extensoes else ""
            raise SemArquivosError(f"Pasta '{pasta.name}' sem arquivos{filtro} para anexar")
        for f in elegiveis:
            self._garantir_local(f)
        return elegiveis

    def _garantir_local(self, arquivo: Path) -> None:
        """No Windows, força o download de arquivos 'só na nuvem' e confere que não está vazio."""
        attrs = getattr(arquivo.stat(), "st_file_attributes", 0)
        if attrs & _ATRIB_NUVEM:
            if self.log:
                self.log.info("Baixando do OneDrive: %s", arquivo.name)
            fim = time.monotonic() + self.timeout_download
            while True:
                try:
                    with open(arquivo, "rb") as fh:  # ler dispara o download
                        fh.read(1)
                    if not getattr(arquivo.stat(), "st_file_attributes", 0) & _ATRIB_NUVEM:
                        break
                except OSError:
                    pass
                if time.monotonic() > fim:
                    raise ArquivoIndisponivelError(
                        f"'{arquivo.name}' não terminou de baixar do OneDrive em "
                        f"{self.timeout_download}s")
                time.sleep(1)
        if os.path.getsize(arquivo) == 0:
            raise ArquivoIndisponivelError(f"'{arquivo.name}' está vazio (0 bytes)")
