import pytest

from src.erros import PlanilhaError
from src.planilha.controle import PlanilhaControle
from tests.conftest import criar_planilha


def test_le_pedido_numerico_e_texto(tmp_path):
    p = criar_planilha(tmp_path / "c.xlsx", [(4500001001, "P-1", None), ("4500001002.0", "P-2", None),
                                             (4500001003.0, "P-3", None)])
    itens = PlanilhaControle(p).carregar()
    assert [i.pedido for i in itens] == ["4500001001", "4500001002.0", "4500001003"]
    # texto com ".0" não é numérico puro -> inválido (não adivinhamos)
    assert itens[1].erro_validacao and "numérico" in itens[1].erro_validacao
    assert itens[0].erro_validacao is None and itens[2].erro_validacao is None


def test_aceita_cabecalho_alternativo(tmp_path):
    p = criar_planilha(tmp_path / "c.xlsx", [("4500001001", "P-1")], cabecalho=("Pedido", "Nº Processo"))
    itens = PlanilhaControle(p).carregar()
    assert itens[0].pedido == "4500001001" and itens[0].processo == "P-1"


def test_cria_colunas_de_saida_quando_faltam(tmp_path):
    p = criar_planilha(tmp_path / "c.xlsx", [("4500001001", "P-1")], cabecalho=("pedido", "processo"))
    pl = PlanilhaControle(p)
    item = pl.carregar()[0]
    pl.atualizar(item, "CONCLUIDO", "ok")
    assert pl.salvar()
    from openpyxl import load_workbook
    cab = [c.value for c in load_workbook(p).active[1]]
    assert cab == ["pedido", "processo", "status", "data_processamento", "observacao"]


def test_colunas_obrigatorias_ausentes(tmp_path):
    p = criar_planilha(tmp_path / "c.xlsx", [("x", "y")], cabecalho=("coluna_a", "coluna_b"))
    with pytest.raises(PlanilhaError, match="obrigatórias"):
        PlanilhaControle(p).carregar()


def test_arquivo_inexistente(tmp_path):
    with pytest.raises(PlanilhaError, match="não encontrada"):
        PlanilhaControle(tmp_path / "nao_existe.xlsx").carregar()


def test_validacoes_vazio_nao_numerico_duplicata_e_conflito(tmp_path):
    p = criar_planilha(tmp_path / "c.xlsx", [
        ("4500001001", "P-1", None),
        ("4500001001", "P-1", None),        # duplicata exata
        ("4500001002", "P-2", None),
        ("4500001002", "P-9", None),        # mesmo pedido, processos diferentes
        ("ABC", "P-3", None),               # não numérico
        ("4500001004", None, None),         # processo vazio
        (None, "P-5", None),                # pedido vazio
        (None, None, None),                 # linha vazia: ignorada
    ])
    it = PlanilhaControle(p).carregar()
    assert len(it) == 7
    assert it[0].erro_validacao is None and not it[0].duplicado
    assert it[1].duplicado
    assert "diferentes" in it[2].erro_validacao and "diferentes" in it[3].erro_validacao
    assert "numérico" in it[4].erro_validacao
    assert "processo vazio" in it[5].erro_validacao
    assert "pedido vazio" in it[6].erro_validacao


def test_deve_processar(tmp_path):
    p = criar_planilha(tmp_path / "c.xlsx", [("1", "a", None), ("2", "b", "pendente"),
                                             ("3", "c", "CONCLUIDO"), ("4", "d", "ERRO")])
    it = PlanilhaControle(p).carregar()
    assert [i.deve_processar() for i in it] == [True, True, False, False]
    assert [i.deve_processar(reprocessar_erros=True) for i in it] == [True, True, False, True]


def test_salvar_com_planilha_aberta_nao_derruba(tmp_path, monkeypatch):
    p = criar_planilha(tmp_path / "c.xlsx", [("4500001001", "P-1", None)])
    pl = PlanilhaControle(p)
    item = pl.carregar()[0]
    pl.atualizar(item, "CONCLUIDO")
    monkeypatch.setattr("src.planilha.controle.time.sleep", lambda s: None)

    from openpyxl.workbook.workbook import Workbook

    def bloqueado(*a, **k):
        raise PermissionError("arquivo em uso")
    monkeypatch.setattr(Workbook, "save", bloqueado)
    assert pl.salvar() is False          # devolve False, sem exceção
    monkeypatch.undo()
    assert pl.salvar() is True           # depois de liberado, salva (alteração continuava pendente)
