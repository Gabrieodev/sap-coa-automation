"""Gera a base FICTÍCIA de demonstração:
  data/controle_coa.xlsx          -> "base do sistema" (só lida pelo robô): PROCESSO na coluna G,
                                     PEDIDO SAP na H, SITUAÇÃO COA na I (critério opcional)
  data/sharepoint_simulado/...    -> pastas por processo, no lugar do SharePoint sincronizado.
                                     O processo da base é '0001/26'; a pasta é '0001-26'.

Rodar de novo ZERA a demonstração (apaga e recria). Cada linha cobre um cenário diferente,
combinando com os cenários do SAP simulado em main.py (--simulado).
"""
import shutil
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "data"
SP = DADOS / "sharepoint_simulado"


def pdf_minimo(texto: str) -> bytes:
    """PDF de 1 página, válido, só para ter arquivo real de teste."""
    stream = f"BT /F1 12 Tf 10 50 Td ({texto}) Tj ET".encode("latin-1")
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 100]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>\nstream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<</Size {len(objs)+1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def coa(pasta: Path, nome: str):
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_bytes(pdf_minimo(f"COA FICTICIO - {nome}"))


def criar_pastas():
    if SP.exists():
        shutil.rmtree(SP)
    SP.mkdir(parents=True)
    # 0001/26: o robô anexa TUDO da pasta (PDFs, Excel, txt), menos lixo (~$, Thumbs.db)
    p = SP / "0001-26"
    coa(p, "COA_0001-26_lote1.pdf")
    coa(p, "COA_0001-26_lote2.pdf")
    (p / "packing list.xlsx").write_bytes("PK ficticio: planilha de packing list".encode("utf-8"))
    (p / "notas internas.txt").write_text("também é anexado (pasta inteira)", encoding="utf-8")
    (p / "~$COA_0001-26_lote1.pdf").write_bytes(b"lixo")
    (p / "Thumbs.db").write_bytes(b"lixo")
    # 0002/26: 1 PDF
    coa(SP / "0002-26", "COA_0002-26.pdf")
    # 0003/26: lote1 já estará anexado no SAP simulado (testa idempotência); lote2 é novo
    coa(SP / "0003-26", "COA_0003-26_lote1.pdf")
    coa(SP / "0003-26", "COA_0003-26_lote2.pdf")
    # 0004/26: SEM pasta (cenário "pasta não encontrada")
    # 0005/26: pasta existe mas só tem lixo (cenário "sem arquivos")
    (SP / "0005-26").mkdir()
    (SP / "0005-26" / "Thumbs.db").write_bytes(b"lixo")
    # 0006/26 / 0007/26: pasta OK; o problema é no SAP (pedido inexistente / bloqueado)
    coa(SP / "0006-26", "COA_0006-26.pdf")
    coa(SP / "0007-26", "COA_0007-26.pdf")
    # 0008/26: pasta com sufixo (plano B: o robô casa pelo início do nome)
    coa(SP / "0008-26 (ANTIGO 1-9145)", "COA_0008-26.pdf")
    # 0011/26: DUAS pastas casam -> ambíguo
    coa(SP / "0011-26 - Fornecedor A", "COA_0011-26_a.pdf")
    coa(SP / "0011-26 - Fornecedor B", "COA_0011-26_b.pdf")
    # 0010/26 e 0012/26 ficam fora do critério da base; as pastas existem mas não são tocadas
    coa(SP / "0010-26", "COA_0010-26.pdf")
    coa(SP / "0012-26", "COA_0012-26.pdf")
    # Processos que NÃO estão na base: o robô nem olha estas pastas
    for fora in ("0090-26", "0091-26", "0092-26"):
        coa(SP / fora, f"COA_{fora}.pdf")


# (processo, pedido, situação COA) — colunas da planilha: G=processo, H=pedido, I=situação
# "PENDENTE" = precisa anexar. Com COA_COL_FILTRO=I e COA_FILTRO_PROCESSAR=PENDENTE só estas valem.
LINHAS = [
    ("0001/26", "4500001001", "PENDENTE"),   # ok: 3 arquivos (+ lixo ignorado)
    ("0002/26", 4500001002, "PENDENTE"),     # ok; pedido numérico na célula
    ("0003/26", "4500001003", "PENDENTE"),   # 1 já anexado -> envia só o lote2
    ("0004/26", "4500001004", "PENDENTE"),   # pasta inexistente -> ERRO
    ("0005/26", "4500001005", "PENDENTE"),   # pasta só com lixo -> ERRO
    ("0006/26", "4500001006", "PENDENTE"),   # pedido inexistente no SAP -> ERRO
    ("0007/26", "4500001007", "PENDENTE"),   # pedido bloqueado -> ERRO
    ("0008/26", "4500001008", "PENDENTE"),   # pasta com sufixo -> ok
    (None, "4500001009", "PENDENTE"),        # processo vazio -> ERRO de validação
    ("0001/26", "4500001001", "PENDENTE"),   # duplicata exata -> IGNORADO
    ("0010/26", "4500001010", "COA ANEXADO"),            # fora do critério -> não é tocada
    ("0011/26", "4500001011", "PENDENTE"),   # duas pastas casam -> ERRO ambíguo
    ("0012/26", "4500001012", "SEM COA NECESSÁRIO"),     # fora do critério -> não é tocada
]

FORNECEDORES = ["Alfa Químicos", "Beta Insumos", "Gama Trading", "Delta Química"]
PRODUTOS = ["Ureia", "Nitrato de K", "MAP", "Sulfato de Mg"]


def criar_planilha():
    wb = Workbook()
    ws = wb.active
    ws.title = "Base de dados COA"
    cab = ["DATA", "FORNECEDOR", "PRODUTO", "NF", "INVOICE", "LOTE",
           "PROCESSO", "PEDIDO SAP", "SITUAÇÃO COA", "OBS. EQUIPE"]
    ws.append(cab)
    fonte = Font(name="Arial", size=10)
    for c in ws[1]:
        c.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
        c.alignment = Alignment(horizontal="center")
    for i, (proc, ped, situacao) in enumerate(LINHAS):
        # colunas A-F e J são "ruído" de propósito: o robô só lê G e H (e I, se o filtro estiver ligado)
        ws.append([f"2026-09-{(i % 28) + 1:02d}", FORNECEDORES[i % 4], PRODUTOS[i % 4],
                   f"NF-{9000 + i}", f"INV-{300 + i}", f"L{i + 1:03d}", proc, ped,
                   situacao, "fictício" if i % 3 == 0 else None])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font = fonte
        row[7].number_format = "0"  # PEDIDO SAP numérico sem notação científica
    for col, w in zip("ABCDEFGHIJ", (12, 18, 16, 11, 11, 8, 20, 16, 24, 14)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    leg = wb.create_sheet("Instruções")
    linhas = [
        ("BASE FICTÍCIA DE DEMONSTRAÇÃO (layout da base real)", True),
        ("Pedidos, processos e fornecedores são inventados.", False),
        ("", False),
        ("Como o robô usa as colunas (a memória dele fica em data\\estado_processamento.csv)", True),
        ("G  PROCESSO     : '0001/26' na base = pasta '0001-26' no SharePoint. (lida)", False),
        ("H  PEDIDO SAP   : número do pedido de compra no SAP. (lida)", False),
        ("I  SITUAÇÃO COA : critério opcional. Para ligar: COA_COL_FILTRO=I e COA_FILTRO_PROCESSAR=PENDENTE.", False),
        ("K-M STATUS/OBS/DATA COA ROBÔ : o robô cria e preenche estas colunas no fim da tabela. (escrita)", False),
        ("As demais colunas não são alteradas. O robô só visita as pastas dos processos que estão aqui;", False),
        ("as pastas 0090-26, 0091-26 e 0092-26 do SharePoint simulado NÃO estão na base e nunca são abertas.", False),
        ("", False),
        ("Cenários cobertos pelas linhas de exemplo", True),
        ("Linha 2: ok, 3 arquivos (PDFs + Excel + txt); lixo (~$, Thumbs.db) é ignorado", False),
        ("Linha 3: pedido numérico na célula", False),
        ("Linha 4: 1 PDF já anexado no SAP -> envia só o que falta", False),
        ("Linha 5: pasta do processo não existe", False),
        ("Linha 6: pasta só com lixo (sem nada para anexar)", False),
        ("Linha 7: pedido inexistente no SAP", False),
        ("Linha 8: pedido bloqueado no SAP", False),
        ("Linha 9: pasta com sufixo no nome ('0008-26 (ANTIGO 1-9145)')", False),
        ("Linha 10: processo vazio", False),
        ("Linha 11: duplicata exata da linha 2", False),
        ("Linha 12: situação 'COA ANEXADO' -> fora do critério (com o filtro ligado)", False),
        ("Linha 13: duas pastas casam com o processo -> ambíguo", False),
        ("Linha 14: situação 'SEM COA NECESSÁRIO' -> fora do critério (com o filtro ligado)", False),
    ]
    for i, (t, neg) in enumerate(linhas, 1):
        c = leg.cell(i, 1, t)
        c.font = Font(name="Arial", size=10, bold=neg)
    leg.column_dimensions["A"].width = 105
    wb.save(DADOS / "controle_coa.xlsx")


if __name__ == "__main__":
    DADOS.mkdir(exist_ok=True)
    criar_pastas()
    criar_planilha()
    (DADOS / "estado_processamento.csv").unlink(missing_ok=True)   # resíduo do modo só-leitura
    print(f"Base fictícia criada em {DADOS}")
