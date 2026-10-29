import pytest

from src.arquivos.provedor import PastaSincronizada
from src.erros import (ArquivoIndisponivelError, PastaProcessoAmbiguaError,
                       PastaProcessoNaoEncontradaError, SemArquivosError)
from tests.conftest import criar_pdf


@pytest.fixture
def prov(tmp_path):
    return PastaSincronizada(tmp_path / "sp", (".pdf",))


def test_pasta_exata_e_filtra_lixo(tmp_path, prov):
    p = tmp_path / "sp" / "PROC-1"
    criar_pdf(p, "b.pdf"); criar_pdf(p, "a.PDF")
    criar_pdf(p, "~$a.pdf"); criar_pdf(p, "x.tmp"); criar_pdf(p, "Thumbs.db"); criar_pdf(p, "n.txt")
    arqs = prov.obter_arquivos("PROC-1")
    assert [a.name for a in arqs] == ["a.PDF", "b.pdf"]  # ordenado, só pdf, sem lixo


def test_casa_pelo_inicio_do_nome_e_ignora_caixa(tmp_path, prov):
    criar_pdf(tmp_path / "sp" / "proc-2026-0008 - Fornecedor", "c.pdf")
    assert prov.obter_arquivos("PROC-2026-0008")[0].name == "c.pdf"


def test_prefixo_nao_confunde_proc1_com_proc10(tmp_path, prov):
    criar_pdf(tmp_path / "sp" / "PROC-10", "dez.pdf")
    with pytest.raises(PastaProcessoNaoEncontradaError):
        prov.obter_arquivos("PROC-1")


def test_exata_tem_prioridade_sobre_parcial(tmp_path, prov):
    criar_pdf(tmp_path / "sp" / "PROC-1", "exata.pdf")
    criar_pdf(tmp_path / "sp" / "PROC-1 - antigo", "velho.pdf")
    assert prov.obter_arquivos("PROC-1")[0].name == "exata.pdf"


def test_ambigua(tmp_path, prov):
    criar_pdf(tmp_path / "sp" / "PROC-5 - A", "a.pdf")
    criar_pdf(tmp_path / "sp" / "PROC-5 - B", "b.pdf")
    with pytest.raises(PastaProcessoAmbiguaError):
        prov.obter_arquivos("PROC-5")


def test_sem_arquivos_elegiveis(tmp_path, prov):
    criar_pdf(tmp_path / "sp" / "PROC-3", "so.txt")
    with pytest.raises(SemArquivosError):
        prov.obter_arquivos("PROC-3")


def test_raiz_inacessivel(tmp_path):
    with pytest.raises(PastaProcessoNaoEncontradaError, match="inacessível"):
        PastaSincronizada(tmp_path / "nao_montado").obter_arquivos("X")


def test_arquivo_vazio_e_rejeitado(tmp_path, prov):
    criar_pdf(tmp_path / "sp" / "PROC-4", "vazio.pdf", conteudo=b"")
    with pytest.raises(ArquivoIndisponivelError, match="vazio"):
        prov.obter_arquivos("PROC-4")


# ---- processo com barra na planilha x pasta com hífen no SharePoint (caso real) ----
@pytest.mark.parametrize("processo,pasta", [
    ("0226/25", "0226-25"),
    ("0226-25", "0226-25"),
    ("0002/23", "0002-23 (ANTIGO 1-9145)"),       # pasta com sufixo
    ("0140\\26", "0140-26"),
    (" 0140/26 ", "0140-26"),
])
def test_barra_do_processo_casa_com_hifen_da_pasta(tmp_path, prov, processo, pasta):
    for nome in ("0226-25", "0002-23 (ANTIGO 1-9145)", "0140-26", "0001-24"):
        criar_pdf(tmp_path / "sp" / nome, "coa.pdf")
    assert prov.localizar_pasta(processo).name == pasta


def test_processo_nao_casa_com_pasta_de_ano_parecido(tmp_path, prov):
    criar_pdf(tmp_path / "sp" / "0001-24", "a.pdf")
    criar_pdf(tmp_path / "sp" / "0001-240", "b.pdf")        # prefixo parecido
    assert prov.localizar_pasta("0001/24").name == "0001-24"
    with pytest.raises(PastaProcessoNaoEncontradaError):
        prov.localizar_pasta("0001/2")                       # 0001-2 não é prefixo de 0001-24
