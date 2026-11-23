"""Ambiente REAL: link do SharePoint -> pasta sincronizada, base mais recente, coluna CL -> CM."""
import os
import sys
import time
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

import config as cfg_mod
import main as main_mod
from src.ambiente import resolver_planilha, resolver_raiz_arquivos
from src.arquivos import sharepoint_local as sp
from src.arquivos.provedor import PastaSincronizada
from src.erros import ErroFatal, PastaProcessoAmbiguaError
from src.planilha.controle import PlanilhaControle
from src.utils.nomes import nomes_pasta_candidatos
from tests.conftest import criar_pdf

LINK_BASE = ("https://iclgroup365.sharepoint.com/:x:/r/sites/ICLBRComexTeam/Shared%20Documents/IMPO-ADS/"
             "Controle%20rob%C3%B4%20COA/DATA%20BASE%20-%202026-11-11T152807.964.xlsx"
             "?d=w40e1251b3e964e21b6ce0958be8b8104&csf=1&web=1&e=8Qscef")


# ------------------------------------------------------------------ link do SharePoint
def test_interpreta_o_link_de_compartilhamento_da_base():
    link = sp.interpretar_link(LINK_BASE)
    assert link.site == "ICLBRComexTeam" and link.biblioteca == "Shared Documents"
    assert link.caminho == ("IMPO-ADS", "Controle robô COA", "DATA BASE - 2026-11-11T152807.964.xlsx")
    assert link.e_arquivo and link.pasta == ("IMPO-ADS", "Controle robô COA")


def test_interpreta_link_de_pasta_com_id_e_link_direto():
    u = ("https://x.sharepoint.com/sites/Comex/Shared%20Documents/Forms/AllItems.aspx?"
         "id=%2Fsites%2FComex%2FShared%20Documents%2FIMPO-ADS%2FDOCS%20PROCESSOS&viewid=1")
    assert sp.interpretar_link(u).pasta == ("IMPO-ADS", "DOCS PROCESSOS")
    assert sp.interpretar_link("https://x.sharepoint.com/sites/Comex/Shared%20Documents/A/B").pasta == ("A", "B")
    with pytest.raises(ValueError):
        sp.interpretar_link("https://example.com/qualquer")


def test_config_padrao_traz_o_link_real_sem_parametros_de_compartilhamento():
    c = cfg_mod.Config()
    assert sp.interpretar_link(c.url_base_controle).pasta == ("IMPO-ADS", "Controle robô COA")
    assert "csf=" not in c.url_base_controle and "?d=" not in c.url_base_controle


LINK_DOCS = ("https://iclgroup365.sharepoint.com/sites/ICLBRComexTeam/Shared%20Documents/Forms/AllItems.aspx?"
             "id=%2Fsites%2FICLBRComexTeam%2FShared%20Documents%2FIMPO%2DADS%2FDOCS%20PROCESSOS%20IMPORTA%C3%87%C3%83O"
             "&viewid=5f9fa3f6%2Ddc8e%2D4629%2D951b%2D349a11ea24db&FolderCTID=0x012000CE3E9B4A1889794E92BF3BF3D0413061"
             "&TeamsCID=b8a18127%2Dd46a%2D46ed%2D9ebb%2D2dd536b8df49&OR=Teams%2DHL&CT=1792675049340")


def test_link_copiado_do_navegador_da_pasta_de_documentos():
    link = sp.interpretar_link(LINK_DOCS)
    assert link.site == "ICLBRComexTeam" and link.pasta == ("IMPO-ADS", "DOCS PROCESSOS IMPORTAÇÃO")
    # o link guardado na config (sem parâmetros de rastreio) aponta para a mesma pasta
    assert sp.interpretar_link(cfg_mod.Config().url_pasta_processos) == \
        sp.LinkSharePoint("ICLBRComexTeam", "Shared Documents", ("IMPO-ADS", "DOCS PROCESSOS IMPORTAÇÃO"))
    assert "ovuser" not in cfg_mod.Config().url_pasta_processos


# ------------------------------------------------------------------ pasta sincronizada
@pytest.fixture
def onedrive(tmp_path):
    """C:\\Users\\voce\\ICL Group\\ICL BR Comex Team - Documents\\IMPO-ADS\\..., como o OneDrive monta."""
    raiz = tmp_path / "ICL Group"
    biblio = raiz / "ICL BR Comex Team - Documents"
    (biblio / "IMPO-ADS" / "Controle robô COA").mkdir(parents=True)
    (biblio / "IMPO-ADS" / "DOCS PROCESSOS IMPORTAÇÃO").mkdir(parents=True)
    (raiz / "Outro Site - Documents").mkdir()
    return raiz, biblio


def test_acha_biblioteca_pelo_nome_do_site_sem_espacos(onedrive):
    raiz, biblio = onedrive
    assert sp.bibliotecas_locais("ICLBRComexTeam", [raiz]) == [biblio]


def test_resolve_pasta_da_base_a_partir_do_link(onedrive):
    raiz, biblio = onedrive
    assert sp.resolver_pasta_local(LINK_BASE, [raiz]) == biblio / "IMPO-ADS" / "Controle robô COA"
    assert sp.resolver_pasta_local(LINK_BASE, []) is None


def test_localiza_pasta_de_documentos_pelo_nome_sem_entrar_nela(onedrive):
    raiz, biblio = onedrive
    docs = biblio / "IMPO-ADS" / "DOCS PROCESSOS IMPORTAÇÃO"
    for i in range(50):
        (docs / f"{i:04d}-26" / "x").mkdir(parents=True)
    assert sp.localizar_pasta_por_nome("docs processos importacao", [biblio]) == docs
    assert sp.localizar_pasta_por_nome("nao existe", [biblio]) is None


def test_base_mais_recente_pelo_carimbo_no_nome_e_ignora_temporarios(tmp_path):
    nomes = ["DATA BASE - 2026-11-10T090000.000.xlsx", "DATA BASE - 2026-11-11T152807.964.xlsx",
             "~$DATA BASE - 2026-11-12T100000.000.xlsx", "outra planilha.xlsx"]
    for n in nomes:
        (tmp_path / n).write_bytes(b"x")
    os.utime(tmp_path / nomes[0], (time.time() + 999, time.time() + 999))   # mtime mais novo NÃO manda
    assert sp.base_mais_recente(tmp_path).name == "DATA BASE - 2026-11-11T152807.964.xlsx"
    assert sp.base_mais_recente(tmp_path / "vazia") is None


def test_base_sem_carimbo_usa_data_de_modificacao(tmp_path):
    (tmp_path / "DATA BASE a.xlsx").write_bytes(b"x")
    novo = tmp_path / "DATA BASE b.xlsx"; novo.write_bytes(b"x")
    os.utime(tmp_path / "DATA BASE a.xlsx", (1, 1))
    assert sp.base_mais_recente(tmp_path) == novo


# ------------------------------------------------------------------ resolução completa (ambiente real)
def test_resolve_base_e_documentos_reais_pelo_link(onedrive, monkeypatch):
    raiz, biblio = onedrive
    base = biblio / "IMPO-ADS" / "Controle robô COA" / "DATA BASE - 2026-11-11T152807.964.xlsx"
    base.write_bytes(b"x")
    monkeypatch.setattr(sp, "raizes_onedrive", lambda *a, **k: [raiz])
    cfg = cfg_mod.Config()
    assert resolver_planilha(cfg) == base
    assert resolver_raiz_arquivos(cfg) == biblio / "IMPO-ADS" / "DOCS PROCESSOS IMPORTAÇÃO"  # pelo link


def test_sem_link_da_pasta_procura_pelo_nome(onedrive, monkeypatch):
    raiz, biblio = onedrive
    monkeypatch.setattr(sp, "raizes_onedrive", lambda *a, **k: [raiz])
    cfg = cfg_mod.Config(url_pasta_processos=None)
    assert resolver_raiz_arquivos(cfg) == biblio / "IMPO-ADS" / "DOCS PROCESSOS IMPORTAÇÃO"


def test_override_por_variavel_de_ambiente_tem_prioridade(onedrive, tmp_path):
    cfg = cfg_mod.Config(planilha=tmp_path, raiz_arquivos=tmp_path / "docs")
    (tmp_path / "DATA BASE - 2026-01-01T000000.000.xlsx").write_bytes(b"x")
    assert resolver_planilha(cfg).name.startswith("DATA BASE")
    assert resolver_raiz_arquivos(cfg) == tmp_path / "docs"


def test_sem_onedrive_para_com_erro_claro(monkeypatch):
    monkeypatch.setattr(sp, "raizes_onedrive", lambda *a, **k: [])
    with pytest.raises(ErroFatal, match="Sincronizar|sincronizada"):
        resolver_planilha(cfg_mod.Config())
    with pytest.raises(ErroFatal, match="sincroniza"):
        resolver_raiz_arquivos(cfg_mod.Config())


def test_main_real_sem_sharepoint_nao_cai_nos_dados_de_demonstracao(tmp_path, monkeypatch):
    """Sem --simulado e sem achar a base real, sai com 2: jamais usa data/controle_coa.xlsx."""
    monkeypatch.setattr(sp, "raizes_onedrive", lambda *a, **k: [])
    for k in ("COA_PLANILHA", "COA_RAIZ_ARQUIVOS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("COA_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("COA_ARQUIVO_ESTADO", str(tmp_path / "estado.csv"))
    monkeypatch.setattr(main_mod, "_conectar_sap_real", lambda cfg, log: (_ for _ in ()).throw(
        AssertionError("conectou ao SAP")))
    monkeypatch.setattr(sys, "argv", ["main.py"])
    assert main_mod.main() == 2
    assert not (tmp_path / "estado.csv").exists()


def test_main_com_pasta_da_base_usa_a_mais_recente(tmp_path, monkeypatch):
    pasta = tmp_path / "controle"; pasta.mkdir()
    for nome, proc in (("DATA BASE - 2026-11-10T000000.000.xlsx", "0001/26"),
                       ("DATA BASE - 2026-11-11T152807.964.xlsx", "0002/26")):
        wb = Workbook(); ws = wb.active; ws.append(["PROCESSO", "PEDIDO SAP"]); ws.append([proc, 4500000001])
        wb.save(pasta / nome)
    criar_pdf(tmp_path / "docs" / "0002-26", "coa.pdf")
    for k, v in {"COA_PLANILHA": pasta, "COA_RAIZ_ARQUIVOS": tmp_path / "docs", "COA_LOGS_DIR": tmp_path / "logs",
                 "COA_ARQUIVO_ESTADO": tmp_path / "estado.csv"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado"])
    assert main_mod.main() == 0
    ws = load_workbook(pasta / "DATA BASE - 2026-11-11T152807.964.xlsx").active
    assert ws["C1"].value == "STATUS COA ROBÔ" and ws["C2"].value == "JÁ ANEXADO"
    assert load_workbook(pasta / "DATA BASE - 2026-11-10T000000.000.xlsx").active.max_column == 2  # antiga intacta


# ------------------------------------------------------------------ pasta com '-' ou '_'
def test_candidatos_de_nome_de_pasta():
    assert nomes_pasta_candidatos("0226/25") == ["0226-25", "0226_25"]
    assert nomes_pasta_candidatos(" 0226 / 25 ") == ["0226-25", "0226_25"]
    assert nomes_pasta_candidatos("0226-25") == ["0226-25"]


@pytest.mark.parametrize("pasta", ["0226-25", "0226_25"])
def test_pasta_com_hifen_ou_underline_e_achada_sem_listar(tmp_path, pasta):
    criar_pdf(tmp_path / "sp" / pasta, "coa.pdf")
    for i in range(30):
        (tmp_path / "sp" / f"{i:04d}-24").mkdir()
    prov = PastaSincronizada(tmp_path / "sp")
    assert prov.obter_arquivos("0226/25")[0].name == "coa.pdf"
    assert prov.listagens == 0


def test_as_duas_variantes_existindo_e_ambiguo(tmp_path):
    criar_pdf(tmp_path / "sp" / "0226-25", "a.pdf"); criar_pdf(tmp_path / "sp" / "0226_25", "b.pdf")
    with pytest.raises(PastaProcessoAmbiguaError):
        PastaSincronizada(tmp_path / "sp").obter_arquivos("0226/25")


def test_pasta_com_underline_e_sufixo_via_plano_b(tmp_path):
    criar_pdf(tmp_path / "sp" / "0002_23 (ANTIGO 1-9145)", "a.pdf")
    assert PastaSincronizada(tmp_path / "sp").obter_arquivos("0002/23")[0].name == "a.pdf"


# ------------------------------------------------------------------ base até CL -> status em CM
def _base_ate_cl(caminho, formatacao_alem=True):
    wb = Workbook(); ws = wb.active
    cab = [f"COL{i}" for i in range(1, 91)]                  # A..CL (90 colunas)
    cab[6], cab[7] = "PROCESSO", "PEDIDO SAP"                # G, H
    ws.append(cab)
    ws.append([None] * 6 + ["0226/25", 4500000001] + [None] * 82)
    if formatacao_alem:                                      # Excel guarda formato em colunas vazias
        ws.cell(1, 120).number_format = "0.00"
    wb.save(caminho)


def test_base_ate_cl_cria_status_em_cm_e_nao_longe_da_tabela(tmp_path):
    p = tmp_path / "b.xlsx"; _base_ate_cl(p)
    pl = PlanilhaControle(p, col_pedido="PEDIDO SAP", col_processo="PROCESSO", col_status="STATUS COA ROBÔ",
                          col_obs="OBS COA ROBÔ", col_data="DATA COA ROBÔ", gravar_na_planilha=True,
                          arquivo_estado=tmp_path / "e.csv")
    it = pl.carregar()[0]
    pl.atualizar(it, "CONCLUIDO", "1 arquivo(s) anexado(s)"); assert pl.salvar()
    ws = load_workbook(p).active
    assert get_column_letter(90) == "CL"
    assert ws["CM1"].value == "STATUS COA ROBÔ" and ws["CM2"].value == "JÁ ANEXADO"
    assert ws["CN1"].value == "OBS COA ROBÔ" and ws["CO1"].value == "DATA COA ROBÔ"
    assert ws["CL1"].value == "COL90"


def test_cabecalho_repetido_nao_e_adivinhado(tmp_path):
    wb = Workbook(); ws = wb.active
    ws.append(["PROCESSO", "PEDIDO SAP", "PEDIDO SAP"]); ws.append(["0226/25", 1, 2]); wb.save(tmp_path / "b.xlsx")
    pl = PlanilhaControle(tmp_path / "b.xlsx", col_pedido="PEDIDO SAP", col_processo="PROCESSO",
                          gravar_na_planilha=False, arquivo_estado=tmp_path / "e.csv")
    with pytest.raises(Exception, match="mais de uma coluna"):
        pl.carregar()


# ------------------------------------------------------------------ estrutura real do PC corporativo
# C:\Users\NSilveir\OneDrive - ICL\ICL BR Comex Team - KPI MENSAL\Base-controle-robo\DATA BASE - ....xlsx
def _pc_corporativo(tmp_path, docs_em):
    raiz = tmp_path / "NSilveir" / "OneDrive - ICL"
    biblio = raiz / "ICL BR Comex Team - KPI MENSAL"
    base = biblio / "Base-controle-robo"
    base.mkdir(parents=True)
    wb = Workbook(); ws = wb.active
    ws.append(["USUÁRIO", "PROCESSO", "PEDIDO SAP"] + [f"C{i}" for i in range(4, 91)])   # até a CL
    ws.append(["Aron", "0226/25", 4501039840] + [None] * 87)
    ws.append(["Aron", "0227/25", 4501039851] + [None] * 87)
    wb.save(base / "DATA BASE - 2026-11-11T152807.964.xlsx")
    docs = raiz.joinpath(*docs_em)
    criar_pdf(docs / "0226-25", "coa.pdf"); criar_pdf(docs / "0226-25", "invoice.xlsx")
    criar_pdf(docs / "0227_25", "coa.pdf")                       # separador '_'
    criar_pdf(docs / "0001-24", "fora_da_base.pdf")              # processo que NÃO está na base
    return raiz, base


@pytest.mark.parametrize("docs_em", [
    ("ICL BR Comex Team - KPI MENSAL", "IMPO-ADS", "DOCS PROCESSOS IMPORTAÇÃO"),   # onde o link manda
    ("Atalhos", "DOCS PROCESSOS IMPORTAÇÃO"),                                       # atalho em outro lugar
])
def test_main_com_o_caminho_do_pc_corporativo(tmp_path, monkeypatch, docs_em):
    raiz, base = _pc_corporativo(tmp_path, docs_em)
    monkeypatch.setattr(sp, "raizes_onedrive", lambda *a, **k: [raiz])
    monkeypatch.setenv("COA_PLANILHA", str(base))                 # a PASTA: vale a DATA BASE mais recente
    monkeypatch.delenv("COA_RAIZ_ARQUIVOS", raising=False)
    monkeypatch.setenv("COA_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("COA_ARQUIVO_ESTADO", str(tmp_path / "estado.csv"))
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado"])
    assert main_mod.main() == 0
    ws = load_workbook(base / "DATA BASE - 2026-11-11T152807.964.xlsx").active
    assert ws["CL1"].value == "C90" and ws["CM1"].value == "STATUS COA ROBÔ"      # status logo após a CL
    assert [ws["CM2"].value, ws["CM3"].value] == ["JÁ ANEXADO", "JÁ ANEXADO"]
    log = next((tmp_path / "logs").glob("execucao_*.log")).read_text(encoding="utf-8")
    assert "0001-24" not in log and "fora_da_base" not in log     # pasta fora da base nem foi tocada


def test_caminho_com_variavel_de_ambiente_e_expandido(tmp_path, monkeypatch):
    monkeypatch.setenv("MEU_PERFIL", str(tmp_path))
    ref = "%MEU_PERFIL%" if os.name == "nt" else "$MEU_PERFIL"
    monkeypatch.setenv("COA_PLANILHA", f"{ref}/OneDrive - ICL/Base-controle-robo")
    assert cfg_mod.carregar().planilha == tmp_path / "OneDrive - ICL" / "Base-controle-robo"


# ------------------------------------------------------------------ trava: --simulado não suja a base real
def _env_base(tmp_path, monkeypatch):
    base = tmp_path / "DATA BASE - 2026-11-11T152807.964.xlsx"
    wb = Workbook(); wb.active.append(["PROCESSO", "PEDIDO SAP"]); wb.active.append(["0226/25", 4501039840]); wb.save(base)
    criar_pdf(tmp_path / "docs" / "0226-25", "coa.pdf")
    for k, v in {"COA_PLANILHA": base, "COA_RAIZ_ARQUIVOS": tmp_path / "docs", "COA_LOGS_DIR": tmp_path / "logs",
                 "COA_ARQUIVO_ESTADO": tmp_path / "estado.csv"}.items():
        monkeypatch.setenv(k, str(v))
    monkeypatch.delenv("COA_PERMITIR_SIMULADO_NA_BASE")           # como no uso real
    return base


def test_simulado_com_base_real_e_recusado_e_nada_e_gravado(tmp_path, monkeypatch):
    base = _env_base(tmp_path, monkeypatch)
    antes = base.read_bytes()
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado"])
    assert main_mod.main() == 2
    assert base.read_bytes() == antes and not (tmp_path / "estado.csv").exists()


def test_simulado_dry_run_com_base_real_e_permitido(tmp_path, monkeypatch):
    base = _env_base(tmp_path, monkeypatch)
    antes = base.read_bytes()
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado", "--dry-run"])
    assert main_mod.main() == 0
    assert base.read_bytes() == antes and not (tmp_path / "estado.csv").exists()


def test_demonstracao_sem_nada_configurado_continua_funcionando(tmp_path, monkeypatch):
    for k in ("COA_PLANILHA", "COA_RAIZ_ARQUIVOS", "COA_PERMITIR_SIMULADO_NA_BASE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("COA_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("COA_ARQUIVO_ESTADO", str(tmp_path / "estado.csv"))
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado", "--dry-run"])   # dry-run: não suja o demo
    assert main_mod.main() in (0, 1)         # 1 = alguns cenários de erro do demo, esperado
    assert "controle_coa.xlsx" in next((tmp_path / "logs").glob("execucao_*.log")).read_text(encoding="utf-8")


# ------------------------------------------------------------------ PC com a biblioteca em português
# C:\Users\tnovaes\ICL\ICL BR Comex Team - Documentos\IMPO-ADS\{Controle robô COA, DOCS PROCESSOS IMPORTAÇÃO}
def _pc_tnovaes(tmp_path):
    raiz = tmp_path / "tnovaes" / "ICL"
    biblio = raiz / "ICL BR Comex Team - Documentos"
    base = biblio / "IMPO-ADS" / "Controle robô COA"
    docs = biblio / "IMPO-ADS" / "DOCS PROCESSOS IMPORTAÇÃO"
    base.mkdir(parents=True)
    wb = Workbook(); ws = wb.active
    ws.append(["USUÁRIO", "PROCESSO", "PEDIDO SAP"] + [f"C{i}" for i in range(4, 91)])
    ws.append(["Aron", "0226/25", 4501039840] + [None] * 87)
    wb.save(base / "DATA BASE - 2026-11-11T152807.964.xlsx")
    criar_pdf(docs / "0226-25", "coa.pdf")
    return raiz, base / "DATA BASE - 2026-11-11T152807.964.xlsx", docs


def test_descobre_sozinho_a_base_e_os_documentos_na_biblioteca_em_portugues(tmp_path, monkeypatch):
    raiz, base, docs = _pc_tnovaes(tmp_path)
    monkeypatch.setattr(sp, "raizes_onedrive", lambda *a, **k: [raiz])
    assert resolver_planilha(cfg_mod.Config()) == base            # pelo link, sem configurar nada
    assert resolver_raiz_arquivos(cfg_mod.Config()) == docs


def test_main_com_os_caminhos_finais_informados(tmp_path, monkeypatch):
    raiz, base, docs = _pc_tnovaes(tmp_path)
    monkeypatch.setenv("TNOVAES_HOME", str(tmp_path / "tnovaes"))
    ref = "%TNOVAES_HOME%" if os.name == "nt" else "$TNOVAES_HOME"
    monkeypatch.setenv("COA_PLANILHA", f"{ref}/ICL/ICL BR Comex Team - Documentos/IMPO-ADS/Controle robô COA/"
                                       "DATA BASE - 2026-11-11T152807.964.xlsx")
    monkeypatch.setenv("COA_RAIZ_ARQUIVOS", f"{ref}/ICL/ICL BR Comex Team - Documentos/IMPO-ADS/DOCS PROCESSOS IMPORTAÇÃO")
    monkeypatch.setenv("COA_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("COA_ARQUIVO_ESTADO", str(tmp_path / "estado.csv"))
    monkeypatch.setattr(sys, "argv", ["main.py", "--simulado"])
    assert main_mod.main() == 0
    ws = load_workbook(base).active
    assert ws["CM1"].value == "STATUS COA ROBÔ" and ws["CM2"].value == "JÁ ANEXADO"
