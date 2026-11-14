"""Novos requisitos: robô guiado só pela base, '/' -> '-', pasta inteira anexada, base só lida."""
import hashlib
import shutil
import sys
from pathlib import Path

import pytest

import main as main_mod
from config import Config
from models.item import CONCLUIDO, ERRO
from src.arquivos.provedor import PastaSincronizada
from src.erros import (AnexoAmbiguoError, PastaProcessoNaoEncontradaError, SemArquivosError)
from src.planilha.controle import PlanilhaControle
from src.planilha.estado import EstadoCsv
from src.sap.simulado import SapSimulado
from src.servicos.processador import Processador
from src.utils.nomes import anexos_pendentes, nome_pasta_processo, normalizar_valor
from tests.conftest import criar_pdf, criar_planilha


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ------------------------------------------------------------------ nome do processo -> pasta
@pytest.mark.parametrize("processo,pasta", [
    ("0226/25", "0226-25"),
    (" 0226 / 25 ", "0226-25"),
    ("0140\\26", "0140-26"),
    ("0226-25", "0226-25"),
    ("0002/23 (ANTIGO 1-9145)", "0002-23 (ANTIGO 1-9145)"),
])
def test_nome_pasta_processo(processo, pasta):
    assert nome_pasta_processo(processo) == pasta


# ------------------------------------------------------------------ só os processos da base
def test_acesso_direto_nao_lista_o_sharepoint(tmp_path, log):
    for i in range(200):                       # biblioteca grande, quase toda fora da base
        (tmp_path / "sp" / f"{i:04d}-24").mkdir(parents=True)
    criar_pdf(tmp_path / "sp" / "0226-25", "coa.pdf")
    prov = PastaSincronizada(tmp_path / "sp", log=log)
    assert [a.name for a in prov.obter_arquivos("0226/25")] == ["coa.pdf"]
    assert prov.listagens == 0                 # nenhuma varredura


def test_plano_b_lista_uma_vez_so_e_so_se_precisar(tmp_path, log):
    criar_pdf(tmp_path / "sp" / "0002-23 (ANTIGO 1-9145)", "a.pdf")
    criar_pdf(tmp_path / "sp" / "0003-23 (ANTIGO)", "b.pdf")
    criar_pdf(tmp_path / "sp" / "0004-23", "c.pdf")
    prov = PastaSincronizada(tmp_path / "sp", log=log)
    prov.obter_arquivos("0004/23")
    assert prov.listagens == 0                 # exata: sem listar
    prov.obter_arquivos("0002/23"); prov.obter_arquivos("0003/23")
    assert prov.listagens == 1                 # sufixo: listou a raiz uma única vez


def test_sem_busca_por_prefixo_nunca_lista(tmp_path):
    criar_pdf(tmp_path / "sp" / "0002-23 (ANTIGO)", "a.pdf")
    prov = PastaSincronizada(tmp_path / "sp", buscar_por_prefixo=False)
    with pytest.raises(PastaProcessoNaoEncontradaError, match="0002-23"):
        prov.obter_arquivos("0002/23")
    assert prov.listagens == 0


def test_profundidade_2_lista_so_as_pastas_intermediarias(tmp_path):
    for ano in ("2024", "2025", "2026"):
        for i in range(30):
            (tmp_path / "sp" / ano / f"{i:04d}-{ano[2:]}").mkdir(parents=True)
    criar_pdf(tmp_path / "sp" / "2025" / "0007-25", "x.pdf")
    prov = PastaSincronizada(tmp_path / "sp", profundidade=2)
    assert prov.obter_arquivos("0007/25")[0].name == "x.pdf"
    assert prov.listagens == 1                 # só a raiz (anos); as pastas de processo não


# ------------------------------------------------------------------ anexar TUDO da pasta
def test_pasta_inteira_menos_lixo(tmp_path, log, caplog):
    p = tmp_path / "sp" / "0226-25"
    for nome in ("coa.pdf", "packing list.xlsx", "invoice.docx", "foto.jpg", "notas.txt"):
        criar_pdf(p, nome)
    for lixo in ("~$invoice.docx", "Thumbs.db", "desktop.ini", "x.tmp", ".DS_Store"):
        criar_pdf(p, lixo)
    (p / "rascunhos").mkdir()
    criar_pdf(p / "rascunhos", "velho.pdf")
    prov = PastaSincronizada(tmp_path / "sp", log=log)
    with caplog.at_level("WARNING", logger="teste"):
        nomes = [a.name for a in prov.obter_arquivos("0226/25")]
    assert nomes == ["coa.pdf", "foto.jpg", "invoice.docx", "notas.txt", "packing list.xlsx"]
    assert "rascunhos" in caplog.text          # subpasta não é anexada, mas avisa


def test_pasta_so_com_lixo_e_erro(tmp_path):
    criar_pdf(tmp_path / "sp" / "0226-25", "Thumbs.db")
    with pytest.raises(SemArquivosError):
        PastaSincronizada(tmp_path / "sp").obter_arquivos("0226/25")


def test_extensoes_opcionais_restringem_e_aceitam_sem_ponto(tmp_path):
    p = tmp_path / "sp" / "0226-25"
    criar_pdf(p, "a.pdf"); criar_pdf(p, "b.xlsx"); criar_pdf(p, "c.docx")
    prov = PastaSincronizada(tmp_path / "sp", ("pdf", ".XLSX"))
    assert [a.name for a in prov.obter_arquivos("0226/25")] == ["a.pdf", "b.xlsx"]


# ------------------------------------------------------------------ idempotência com vários tipos
def _arqs(*nomes):
    return [Path(n) for n in nomes]


def test_anexos_pendentes_basico():
    arqs = _arqs("a.pdf", "b.xlsx")
    assert anexos_pendentes(arqs, []) == arqs
    assert anexos_pendentes(arqs, ["A", "b.xlsx"]) == []        # com e sem extensão, qualquer caixa


def test_anexos_pendentes_mesmo_nome_base():
    arqs = _arqs("COA.pdf", "COA.xlsx")
    assert anexos_pendentes(arqs, []) == arqs                    # nenhum -> ambos
    assert anexos_pendentes(arqs, ["COA", "COA"]) == []          # dois títulos -> ambos presentes
    assert anexos_pendentes(arqs, ["COA.pdf", "COA.xlsx"]) == [] # nome completo
    with pytest.raises(AnexoAmbiguoError):
        anexos_pendentes(arqs, ["COA"])                          # só um: qual falta?
    assert anexos_pendentes(arqs, ["COA.pdf"]) == _arqs("COA.xlsx")  # nome completo resolve
    assert anexos_pendentes(arqs, ["COA.pdf", "COA"]) == []          # um completo + um só nome-base


@pytest.mark.parametrize("a,b", [("  Aprovado ", "APROVADO"), ("Não precisa", "NAO PRECISA"),
                                 ("", "<VAZIO>"), (None, "<VAZIO>")])
def test_normalizar_valor(a, b):
    assert normalizar_valor(a) == b


# ------------------------------------------------------------------ critério da base (opcional)
CAB = ("pedido_sap", "processo", "status", "situacao_coa")


def _montar_com_criterio(tmp_path, log, linhas, **cfg_kw):
    cfg = Config(planilha=tmp_path / "base.xlsx", raiz_arquivos=tmp_path / "sp",
                 logs_dir=tmp_path / "logs", col_filtro="situacao_coa", **cfg_kw)
    criar_planilha(cfg.planilha, linhas, cabecalho=CAB)
    for _, proc, _, _ in linhas:
        criar_pdf(cfg.raiz_arquivos / proc.replace("/", "-"), "coa.pdf")
    pl = PlanilhaControle(cfg.planilha, log=log, col_filtro=cfg.col_filtro)
    return cfg, pl, PastaSincronizada(cfg.raiz_arquivos, log=log)


LINHAS = [("4500000001", "0001/26", None, "SEM COA"), ("4500000002", "0002/26", None, "Com COA"),
          ("4500000003", "0003/26", None, None), ("4500000004", "0004/26", None, "sem coa ")]


def test_filtro_processar_ignora_o_resto_sem_tocar_em_nada(tmp_path, log):
    cfg, pl, prov = _montar_com_criterio(tmp_path, log, LINHAS, filtro_processar=("sem coa",))
    sap = SapSimulado()
    r = Processador(cfg, pl, prov, sap, log).executar()
    assert [x.item.pedido for x in r.resultados] == ["4500000001", "4500000004"]
    assert [c[1] for c in sap.chamadas if c[0] == "abrir"] == ["4500000001", "4500000004"]


def test_filtro_ignorar_e_celula_em_branco(tmp_path, log):
    cfg, pl, prov = _montar_com_criterio(tmp_path, log, LINHAS, filtro_ignorar=("com coa", "<vazio>"))
    r = Processador(cfg, pl, prov, SapSimulado(), log).executar()
    assert [x.item.pedido for x in r.resultados] == ["4500000001", "4500000004"]


def test_sem_filtro_configurado_toda_linha_da_base_vale(tmp_path, log):
    cfg, pl, prov = _montar_com_criterio(tmp_path, log, LINHAS)
    cfg.col_filtro = None
    r = Processador(cfg, pl, prov, SapSimulado(), log).executar()
    assert len(r.resultados) == 4


def test_coluna_de_filtro_inexistente_e_recusada(tmp_path, log):
    criar_planilha(tmp_path / "b.xlsx", LINHAS, cabecalho=CAB)
    with pytest.raises(Exception, match="nao_existe"):
        PlanilhaControle(tmp_path / "b.xlsx", log=log, col_filtro="nao_existe").carregar()


# ------------------------------------------------------------------ vários tipos no processador
def _proc(tmp_path, log, sap, arquivos):
    cfg = Config(planilha=tmp_path / "base.xlsx", raiz_arquivos=tmp_path / "sp", logs_dir=tmp_path / "logs")
    criar_planilha(cfg.planilha, [("4500000001", "0226/25", None)])
    for nome in arquivos:
        criar_pdf(cfg.raiz_arquivos / "0226-25", nome)
    return Processador(cfg, PlanilhaControle(cfg.planilha, log=log),
                       PastaSincronizada(cfg.raiz_arquivos, log=log), sap, log)


def test_anexa_todos_os_tipos_e_segunda_rodada_nao_duplica(tmp_path, log):
    sap = SapSimulado()
    r = _proc(tmp_path, log, sap, ["COA.pdf", "COA.xlsx", "invoice.docx"]).executar()
    assert r.contagem() == {CONCLUIDO: 1}
    assert sorted(c[2] for c in sap.chamadas if c[0] == "anexar") == ["COA.pdf", "COA.xlsx", "invoice.docx"]
    # base regerada pelo sistema (status em branco de novo): nada deve ser reanexado
    antes = len([c for c in sap.chamadas if c[0] == "anexar"])
    _proc(tmp_path, log, sap, []).executar()
    assert len([c for c in sap.chamadas if c[0] == "anexar"]) == antes


def test_anexo_parcial_com_mesmo_nome_base_vira_erro_para_conferir(tmp_path, log):
    sap = SapSimulado(anexos_iniciais={"4500000001": ["COA"]})
    r = _proc(tmp_path, log, sap, ["COA.pdf", "COA.xlsx"]).executar()
    assert r.resultados[0].status == ERRO and "conferir manualmente" in r.resultados[0].mensagem
    assert not [c for c in sap.chamadas if c[0] == "anexar"]


# ------------------------------------------------------------------ base só lida (cópia local)
def test_base_so_lida_nao_e_alterada_e_nao_deixa_resto(tmp_path, log):
    criar_planilha(tmp_path / "base.xlsx", [("4500000001", "0226/25", None)])
    antes = sha(tmp_path / "base.xlsx")
    pl = PlanilhaControle(tmp_path / "base.xlsx", log=log, gravar_na_planilha=False,
                          arquivo_estado=tmp_path / "estado.csv")
    assert [i.pedido for i in pl.carregar()] == ["4500000001"]
    assert sha(tmp_path / "base.xlsx") == antes
    assert not list(tmp_path.glob("*.tmp")) and not list(tmp_path.glob("*.robo.tmp"))


def test_base_em_uso_pelo_onedrive_tenta_de_novo(tmp_path, log, monkeypatch):
    criar_planilha(tmp_path / "base.xlsx", [("4500000001", "0226/25", None)])
    real, chamadas = shutil.copyfile, []

    def instavel(src, dst, *a, **k):
        chamadas.append(1)
        if len(chamadas) < 3:
            raise PermissionError("em uso")
        return real(src, dst, *a, **k)
    monkeypatch.setattr("src.planilha.controle.shutil.copyfile", instavel)
    monkeypatch.setattr("src.planilha.controle.time.sleep", lambda s: None)
    pl = PlanilhaControle(tmp_path / "base.xlsx", log=log, gravar_na_planilha=False,
                          arquivo_estado=tmp_path / "e.csv")
    assert len(pl.carregar()) == 1 and len(chamadas) == 3


# ------------------------------------------------------------------ main ponta a ponta
def test_main_ponta_a_ponta_base_do_sistema(tmp_path, monkeypatch):
    sp = tmp_path / "sp"
    for nome, arqs in {"0226-25": ["coa.pdf", "invoice.xlsx"], "0227-25": ["coa.pdf"],
                       "9999-25": ["fora_da_base.pdf"]}.items():   # 9999-25 NÃO está na base
        for a in arqs:
            criar_pdf(sp / nome, a)
    base = criar_planilha(tmp_path / "base.xlsx",
                          [("4500002001", "0226/25", None, "SEM COA"),
                           ("4500002002", "0227/25", None, "COM COA")], cabecalho=CAB)
    antes = sha(base)
    for k, v in {"COA_PLANILHA": base, "COA_RAIZ_ARQUIVOS": sp, "COA_LOGS_DIR": tmp_path / "logs",
                 "COA_ARQUIVO_ESTADO": tmp_path / "estado.csv", "COA_COL_FILTRO": "situacao_coa",
                 "COA_COL_PEDIDO": "pedido_sap", "COA_COL_PROCESSO": "processo",
                 "COA_GRAVAR_STATUS_NA_PLANILHA": "nao",
                 "COA_FILTRO_PROCESSAR": "SEM COA"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado"])
    assert main_mod.main() == 0
    assert sha(base) == antes                                   # base do sistema intacta
    est = EstadoCsv(tmp_path / "estado.csv")
    assert est.obter("4500002001", "0226/25")[0] == "CONCLUIDO"
    assert est.obter("4500002002", "0227/25") is None           # fora do critério
    log_txt = next((tmp_path / "logs").glob("execucao_*.log")).read_text(encoding="utf-8")
    assert "fora do critério" in log_txt and "9999-25" not in log_txt
    assert main_mod.main() == 0                                 # 2ª rodada: nada a fazer


# ------------------------------------------------------------------ ME22N: sair da transação ao terminar
def test_processador_encerra_a_sessao_sap_ao_terminar(tmp_path, log):
    sap = SapSimulado()
    r = _proc(tmp_path, log, sap, ["COA.pdf"]).executar()
    assert r.contagem() == {CONCLUIDO: 1}
    assert sap.chamadas[-1] == ("encerrar",)            # libera o bloqueio do último pedido


def test_processador_nao_encerra_se_nunca_tocou_no_sap(tmp_path, log):
    sap = SapSimulado()
    _proc(tmp_path, log, sap, []).executar()            # pasta inexistente: erro antes do SAP
    assert not [c for c in sap.chamadas if c[0] in ("abrir", "anexar", "encerrar")]


def test_falha_ao_encerrar_nao_muda_o_resultado(tmp_path, log):
    class SapQueFalhaAoEncerrar(SapSimulado):
        def encerrar(self):
            raise RuntimeError("sessão caiu")
    r = _proc(tmp_path, log, SapQueFalhaAoEncerrar(), ["COA.pdf"]).executar()
    assert r.contagem() == {CONCLUIDO: 1}
