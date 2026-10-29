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
    def __init__(self, raiz: Path, extensoes: tuple[str, ...] = (".pdf",),
                 timeout_download: int = 60, log=None, profundidade: int = 1):
        """profundidade=1: as pastas de processo ficam direto na raiz. 2: dentro de uma
        subpasta da raiz (ex.: por ano), e assim por diante."""
        self.raiz = Path(raiz)
        self.profundidade = max(int(profundidade), 1)
        self._cache_pastas: list[Path] | None = None
        self.extensoes = tuple(e.lower() for e in extensoes)
        self.timeout_download = timeout_download
        self.log = log

    def _listar_pastas(self) -> list[Path]:
        """Pastas candidatas até `profundidade` níveis. Listadas uma vez por execução."""
        if self._cache_pastas is None:
            achadas, nivel = [], [self.raiz]
            for _ in range(self.profundidade):
                proximo = []
                for base in nivel:
                    try:
                        filhos = [p for p in base.iterdir() if p.is_dir()]
                    except OSError:
                        continue
                    achadas.extend(filhos)
                    proximo.extend(filhos)
                nivel = proximo
            self._cache_pastas = achadas
        return self._cache_pastas

    def localizar_pasta(self, processo: str) -> Path:
        if not self.raiz.exists():
            raise PastaProcessoNaoEncontradaError(
                f"Pasta raiz de arquivos inacessível: {self.raiz} (OneDrive sincronizado?)")
        subpastas = self._listar_pastas()
        alvo = _chave(processo)

        exatas = [p for p in subpastas if _chave(p.name) == alvo]
        if len(exatas) == 1:
            return exatas[0]

        # "PROC-2026-0008 - Fornecedor X": o nome começa com o número do processo,
        # seguido de separador (evita 'PROC-1' casar com 'PROC-10')
        padrao = re.compile(rf"^{re.escape(alvo)}(?![0-9a-z])")
        parciais = [p for p in subpastas if padrao.match(_chave(p.name))]
        candidatas = exatas or parciais
        if len(candidatas) == 1:
            return candidatas[0]
        if len(candidatas) > 1:
            raise PastaProcessoAmbiguaError(
                f"{len(candidatas)} pastas casam com '{processo}': "
                f"{[str(p.relative_to(self.raiz)) for p in candidatas]}")
        raise PastaProcessoNaoEncontradaError(f"Nenhuma pasta para o processo '{processo}'")

    def obter_arquivos(self, processo: str) -> list[Path]:
        pasta = self.localizar_pasta(processo)
        elegiveis = []
        for f in sorted(pasta.iterdir()):
            if not f.is_file():
                continue
            nome = f.name.lower()
            if nome.startswith("~$") or nome.startswith(".") or nome in _IGNORAR_NOMES:
                continue
            if nome.endswith((".tmp", ".crdownload", ".partial")):
                continue
            if f.suffix.lower() not in self.extensoes:
                continue
            elegiveis.append(f)
        if not elegiveis:
            raise SemArquivosError(
                f"Pasta '{pasta.name}' sem arquivos {self.extensoes} para anexar")
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
