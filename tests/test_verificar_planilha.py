import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table

from src.utils.verificar_planilha import analisar

RAIZ = Path(__file__).resolve().parents[1]


def planilha_simples(p, grafico=False):
    wb = Workbook(); ws = wb.active
    ws.append(["PROCESSO", "PEDIDO SAP", "SOMA"])
    for i in range(1, 6):
        ws.append([f"000{i}/26", 4500000000 + i, f"=B{i+1}+1"])
    ws.add_table(Table(displayName="Base", ref="A1:C6"))
    dv = DataValidation(type="list", formula1='"x,y"'); ws.add_data_validation(dv); dv.add("D2:D6")
    ws.freeze_panes = "A2"; ws.merge_cells("E1:F1")
    if grafico:
        ws.add_chart(BarChart(), "H2")
    wb.save(p)
    return p


def injetar(p, **partes):
    with zipfile.ZipFile(p, "a") as z:
        for nome, conteudo in partes.items():
            z.writestr(nome.replace("__", "/").replace("_", "."), conteudo)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def test_planilha_simples_e_segura(tmp_path):
    rel = analisar(planilha_simples(tmp_path / "a.xlsx"))
    assert not rel.tem_alguma_perda and rel.celulas_comparadas > 0
    assert "seguro para gravar" in rel.texto()


def test_detecta_power_query_slicers_e_comentarios_encadeados(tmp_path):
    p = planilha_simples(tmp_path / "a.xlsx")
    with zipfile.ZipFile(p, "a") as z:
        z.writestr("xl/connections.xml", "<c/>")
        z.writestr("customXml/item1.xml", "<x/>")
        z.writestr("xl/slicers/slicer1.xml", "<s/>")
        z.writestr("xl/threadedComments/t1.xml", "<t/>")
    rel = analisar(p)
    perdidos = {a.descricao for a in rel.achados if a.nivel == "PERDIDO"}
    assert any("Power Query" in d for d in perdidos)
    assert any("slicers" in d for d in perdidos) and any("comentários encadeados" in d for d in perdidos)
    assert rel.tem_perda_grave and "PERDERIA" in rel.texto()


def test_grafico_e_reescrito_mas_nao_e_perda_grave(tmp_path):
    rel = analisar(planilha_simples(tmp_path / "a.xlsx", grafico=True))
    assert any(a.nivel == "REESCRITO" and "gráficos" in a.descricao for a in rel.achados)
    assert not rel.tem_perda_grave
    assert "reescritos" in rel.texto()


def test_nao_altera_o_arquivo_original(tmp_path):
    p = planilha_simples(tmp_path / "a.xlsx", grafico=True)
    antes = sha(p)
    analisar(p)
    assert sha(p) == antes and not list(tmp_path.glob("*.tmp"))


def test_script_de_linha_de_comando_codigos_de_saida(tmp_path):
    ok = planilha_simples(tmp_path / "ok.xlsx")
    ruim = planilha_simples(tmp_path / "ruim.xlsx")
    injetar(ruim, xl__connections_xml="<c/>")
    cmd = [sys.executable, str(RAIZ / "scripts" / "verificar_planilha.py")]
    r_ok = subprocess.run(cmd + [str(ok)], capture_output=True, text=True, cwd=RAIZ)
    r_ruim = subprocess.run(cmd + [str(ruim)], capture_output=True, text=True, cwd=RAIZ)
    assert r_ok.returncode == 0 and "seguro" in r_ok.stdout
    assert r_ruim.returncode == 1 and "Power Query" in r_ruim.stdout
