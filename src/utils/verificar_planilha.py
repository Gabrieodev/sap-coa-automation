"""Simula a gravação do robô numa CÓPIA da planilha e mostra o que seria perdido.

O robô grava com openpyxl, que reescreve o arquivo inteiro: preserva células, fórmulas,
formatação, tabelas, validações etc., mas descarta recursos que não conhece (conexões de dados /
Power Query, segmentações, comentários encadeados, formas...). Esta verificação abre uma cópia,
regrava com a mesma biblioteca e compara as partes internas do .xlsx e o conteúdo das células.
O arquivo original NUNCA é alterado.
"""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

# (prefixo dentro do .xlsx, descrição, grave?)  grave=True: perder isso costuma importar
PARTES = [
    ("xl/connections.xml", "conexões de dados / Power Query", True),
    ("xl/queryTables/", "tabelas de consulta (Power Query)", True),
    ("customXml/", "metadados do Power Query / Power Pivot", True),
    ("xl/model/", "Modelo de Dados (Power Pivot)", True),
    ("xl/slicers/", "segmentações de dados (slicers)", True),
    ("xl/slicerCaches/", "cache de segmentações de dados", True),
    ("xl/timelines/", "linhas do tempo (timelines)", True),
    ("xl/threadedComments/", "comentários encadeados", True),
    ("xl/persons/", "autores de comentários encadeados", False),
    ("xl/vbaProject.bin", "macros VBA", True),
    ("xl/externalLinks/", "vínculos com outras planilhas", True),
    ("xl/ctrlProps/", "controles de formulário", True),
    ("xl/activeX/", "controles ActiveX", True),
    ("xl/pivotTables/", "tabelas dinâmicas", False),
    ("xl/pivotCache/", "cache de tabelas dinâmicas", False),
    ("xl/charts/", "gráficos", False),
    ("xl/media/", "imagens", False),
    ("xl/drawings/", "desenhos (formas, caixas de texto, imagens, gráficos)", False),
    ("xl/tables/", "tabelas do Excel", False),
    ("docProps/custom.xml", "propriedades personalizadas (ex.: rótulo de confidencialidade)", True),
]
# partes que a biblioteca LÊ e REESCREVE: não somem, mas podem perder detalhes de formatação
REESCRITAS = {"xl/charts/", "xl/drawings/", "xl/media/", "xl/pivotTables/", "xl/pivotCache/"}


@dataclass
class Achado:
    nivel: str          # "PERDIDO" | "PARCIAL" | "REESCRITO" | "DIFERENTE"
    descricao: str
    antes: int = 0
    depois: int = 0
    grave: bool = False


@dataclass
class Relatorio:
    arquivo: Path
    achados: list[Achado] = field(default_factory=list)
    celulas_comparadas: int = 0

    @property
    def tem_perda_grave(self) -> bool:
        return any(a.nivel in ("PERDIDO", "PARCIAL", "DIFERENTE") and a.grave for a in self.achados)

    @property
    def tem_alguma_perda(self) -> bool:
        return any(a.nivel in ("PERDIDO", "PARCIAL", "DIFERENTE") for a in self.achados)

    def texto(self) -> str:
        linhas = [f"Arquivo analisado: {self.arquivo}", f"Células comparadas: {self.celulas_comparadas}", ""]
        if not self.achados:
            linhas.append("✓ Nada foi perdido na regravação de teste.")
        for a in self.achados:
            marca = {"PERDIDO": "✗", "PARCIAL": "✗", "DIFERENTE": "✗", "REESCRITO": "~"}[a.nivel]
            qtd = f" ({a.antes} → {a.depois})" if a.nivel in ("PERDIDO", "PARCIAL") else ""
            linhas.append(f"{marca} {a.nivel:9} {a.descricao}{qtd}")
        linhas.append("")
        if self.tem_perda_grave:
            linhas.append("RESULTADO: a gravação via openpyxl PERDERIA recursos importantes desta planilha.")
            linhas.append("Não grave no arquivo original. Use COA_GRAVAR_STATUS_NA_PLANILHA=nao (CSV) ou outra forma de gravação.")
        elif self.tem_alguma_perda:
            linhas.append("RESULTADO: há perdas; avalie se importam antes de gravar no arquivo original.")
        elif any(a.nivel == "REESCRITO" for a in self.achados):
            linhas.append("RESULTADO: nada some, mas gráficos/desenhos são reescritos e podem mudar de aparência. Confira numa cópia.")
        else:
            linhas.append("RESULTADO: seguro para gravar via openpyxl (conforme este teste).")
        return "\n".join(linhas)


def _contar(caminho: Path) -> dict[str, int]:
    with zipfile.ZipFile(caminho) as z:
        nomes = z.namelist()
    return {prefixo: sum(1 for n in nomes if n == prefixo or (prefixo.endswith("/") and n.startswith(prefixo)))
            for prefixo, _, _ in PARTES}


def _propriedades(ws) -> dict:
    return {
        "células mescladas": len(ws.merged_cells.ranges),
        "validações de dados": len(ws.data_validations.dataValidation) if ws.data_validations else 0,
        "formatações condicionais": len(ws.conditional_formatting),
        "tabelas do Excel": len(ws.tables),
        "filtro automático": ws.auto_filter.ref,
        "painéis congelados": ws.freeze_panes,
        "estado da aba": ws.sheet_state,
        "larguras de coluna": {k: round(v.width or 0, 2) for k, v in ws.column_dimensions.items()},
    }


def analisar(origem: Path) -> Relatorio:
    origem = Path(origem)
    rel = Relatorio(arquivo=origem)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        copia, regravado = tmp / f"original{origem.suffix}", tmp / f"regravado{origem.suffix}"
        shutil.copy2(origem, copia)  # só lemos a cópia
        load_workbook(copia, keep_vba=origem.suffix.lower() == ".xlsm").save(regravado)

        antes, depois = _contar(copia), _contar(regravado)
        for prefixo, descricao, grave in PARTES:
            a, d = antes[prefixo], depois[prefixo]
            if a and not d:
                rel.achados.append(Achado("PERDIDO", descricao, a, d, grave))
            elif a and d < a:
                rel.achados.append(Achado("PARCIAL", descricao, a, d, grave))
            elif a and prefixo in REESCRITAS:
                rel.achados.append(Achado("REESCRITO", descricao + " (reescritos pela biblioteca)", a, d))

        wa, wb_ = load_workbook(copia), load_workbook(regravado)
        if wa.sheetnames != wb_.sheetnames:
            rel.achados.append(Achado("DIFERENTE", f"abas: {wa.sheetnames} → {wb_.sheetnames}", grave=True))
        if len(wa.defined_names) != len(wb_.defined_names):
            rel.achados.append(Achado("DIFERENTE", "nomes definidos", len(wa.defined_names), len(wb_.defined_names)))
        for nome in wa.sheetnames:
            if nome not in wb_.sheetnames:
                continue
            sa, sb = wa[nome], wb_[nome]
            diferentes = 0
            for ra, rb in zip(sa.iter_rows(values_only=True), sb.iter_rows(values_only=True)):
                rel.celulas_comparadas += len(ra)
                diferentes += sum(1 for x, y in zip(ra, rb) if x != y)
            if sa.max_row != sb.max_row or diferentes:
                rel.achados.append(Achado("DIFERENTE", f"aba '{nome}': {diferentes} célula(s) com valor/fórmula diferente",
                                          grave=True))
            pa, pb = _propriedades(sa), _propriedades(sb)
            for chave in pa:
                if pa[chave] != pb[chave]:
                    rel.achados.append(Achado("DIFERENTE", f"aba '{nome}': {chave} mudou ({pa[chave]!r} → {pb[chave]!r})"[:200]))
    return rel
