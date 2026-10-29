"""Gera a base FICTÍCIA de demonstração:
  data/controle_coa.xlsx          -> planilha no layout da base real: PROCESSO na coluna G,
                                     PEDIDO SAP na H, STATUS na I (as demais o robô ignora)
  data/sharepoint_simulado/...    -> pastas por processo, no lugar do SharePoint sincronizado

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
    # 0001: 2 PDFs + lixo que o robô deve ignorar (temporário do Office, Thumbs.db, .txt)
    p = SP / "PROC-2026-0001"
    coa(p, "COA_PROC-2026-0001_lote1.pdf")
    coa(p, "COA_PROC-2026-0001_lote2.pdf")
    (p / "~$COA_PROC-2026-0001_lote1.pdf").write_bytes(b"lixo")
    (p / "Thumbs.db").write_bytes(b"lixo")
    (p / "notas internas.txt").write_text("não é para anexar", encoding="utf-8")
    # 0002: 1 PDF
    coa(SP / "PROC-2026-0002", "COA_PROC-2026-0002.pdf")
    # 0003: lote1 já estará anexado no SAP simulado (testa idempotência); lote2 é novo
    coa(SP / "PROC-2026-0003", "COA_PROC-2026-0003_lote1.pdf")
    coa(SP / "PROC-2026-0003", "COA_PROC-2026-0003_lote2.pdf")
    # 0004: SEM pasta (cenário "pasta não encontrada")
    # 0005: pasta existe mas sem PDF (cenário "sem arquivos")
    (SP / "PROC-2026-0005").mkdir()
    (SP / "PROC-2026-0005" / "rascunho.txt").write_text("sem pdf", encoding="utf-8")
    # 0006 / 0007: pasta OK; o problema é no SAP (pedido inexistente / bloqueado)
    coa(SP / "PROC-2026-0006", "COA_PROC-2026-0006.pdf")
    coa(SP / "PROC-2026-0007", "COA_PROC-2026-0007.pdf")
    # 0008: nome da pasta com sufixo (o robô casa pelo início do nome)
    coa(SP / "PROC-2026-0008 - Fornecedor Alfa", "COA_PROC-2026-0008.pdf")
    # 0011: DUAS pastas casam -> ambíguo
    coa(SP / "PROC-2026-0011 - Fornecedor A", "COA_PROC-2026-0011_a.pdf")
    coa(SP / "PROC-2026-0011 - Fornecedor B", "COA_PROC-2026-0011_b.pdf")
    # 0010 já está CONCLUIDO na planilha; pasta existe, mas não deve ser tocada
    coa(SP / "PROC-2026-0010", "COA_PROC-2026-0010.pdf")


# (processo, pedido, status inicial) — colunas da planilha: G=processo, H=pedido, I=status
LINHAS = [
    ("PROC-2026-0001", "4500001001", None),   # ok, 2 arquivos (+ lixo ignorado)
    ("PROC-2026-0002", 4500001002, None),     # ok; pedido numérico na célula
    ("PROC-2026-0003", "4500001003", None),   # 1 já anexado -> envia só o lote2
    ("PROC-2026-0004", "4500001004", None),   # pasta inexistente -> ERRO
    ("PROC-2026-0005", "4500001005", None),   # pasta sem PDF -> ERRO
    ("PROC-2026-0006", "4500001006", None),   # pedido inexistente no SAP -> ERRO
    ("PROC-2026-0007", "4500001007", None),   # pedido bloqueado -> ERRO
    ("PROC-2026-0008", "4500001008", None),   # pasta com sufixo -> ok
    (None, "4500001009", None),               # processo vazio -> ERRO de validação
    ("PROC-2026-0001", "4500001001", None),   # duplicata exata -> IGNORADO
    ("PROC-2026-0010", "4500001010", "JÁ ANEXADO"),  # já anexado -> pulado
    ("PROC-2026-0011", "4500001011", None),   # duas pastas casam -> ERRO ambíguo
    ("PROC-2026-0012", "4500001012", "AGUARDANDO FORNECEDOR"),  # texto manual -> pulado, intocado
]

FORNECEDORES = ["Alfa Químicos", "Beta Insumos", "Gama Trading", "Delta Química"]
PRODUTOS = ["Ureia", "Nitrato de K", "MAP", "Sulfato de Mg"]


def criar_planilha():
    wb = Workbook()
    ws = wb.active
    ws.title = "Base de dados COA"
    cab = ["DATA", "FORNECEDOR", "PRODUTO", "NF", "INVOICE", "LOTE",
           "PROCESSO", "PEDIDO SAP", "STATUS", "OBS. EQUIPE"]
    ws.append(cab)
    fonte = Font(name="Arial", size=10)
    for c in ws[1]:
        c.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
        c.alignment = Alignment(horizontal="center")
    for i, (proc, ped, status) in enumerate(LINHAS):
        # colunas A-F e J são "ruído" de propósito: o robô só lê G e H e só ESCREVE na I
        ws.append([f"2026-09-{(i % 28) + 1:02d}", FORNECEDORES[i % 4], PRODUTOS[i % 4],
                   f"NF-{9000 + i}", f"INV-{300 + i}", f"L{i + 1:03d}", proc, ped,
                   status, "fictício" if i % 3 == 0 else None])
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
        ("Como o robô usa as colunas", True),
        ("G  PROCESSO    : nome (ou início do nome) da pasta do processo no SharePoint. (lida)", False),
        ("H  PEDIDO SAP  : número do pedido de compra no SAP. (lida)", False),
        ("I  STATUS      : em BRANCO = o robô anexa; o robô escreve 'JÁ ANEXADO' ou 'ERRO'. (escrita)", False),
        ("                 Qualquer outro texto digitado (ex.: 'AGUARDANDO FORNECEDOR') = linha pulada.", False),
        ("As demais colunas são ignoradas e não são alteradas.", False),
        ("", False),
        ("Cenários cobertos pelas linhas de exemplo", True),
        ("Linha 2: ok, 2 PDFs (a pasta também tem lixo que deve ser ignorado)", False),
        ("Linha 3: pedido numérico na célula", False),
        ("Linha 4: 1 PDF já anexado no SAP -> envia só o que falta", False),
        ("Linha 5: pasta do processo não existe", False),
        ("Linha 6: pasta sem PDF", False),
        ("Linha 7: pedido inexistente no SAP", False),
        ("Linha 8: pedido bloqueado no SAP", False),
        ("Linha 9: pasta com sufixo no nome ('PROC-2026-0008 - Fornecedor Alfa')", False),
        ("Linha 10: processo vazio", False),
        ("Linha 11: duplicata exata da linha 2", False),
        ("Linha 12: já marcada 'JÁ ANEXADO' -> pulada", False),
        ("Linha 13: duas pastas casam com o processo -> ambíguo", False),
        ("Linha 14: texto manual no status -> pulada e preservada", False),
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
