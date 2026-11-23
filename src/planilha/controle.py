"""Leitura e atualização da planilha de controle (pedido SAP <-> processo).

Colunas lidas: PROCESSO e PEDIDO SAP (por letra ou nome de cabeçalho). O andamento do robô vai
numa coluna de STATUS ao lado (modo padrão) ou, opcionalmente, num CSV separado.

Status na planilha (comparação sem acento/caixa):
  em branco / PENDENTE      -> o robô processa
  JÁ ANEXADO (ou CONCLUIDO) -> pulada
  ERRO                      -> pulada, a não ser com --reprocessar-erros
  qualquer outro texto      -> pulada e NUNCA sobrescrita (ex.: "SEM COA", "AGUARDANDO")

Cuidados porque a planilha é compartilhada (ver `_gravar_na_planilha`):
  * os valores são lidos com data_only=True (fórmulas viram o valor calculado);
  * na hora de gravar, o arquivo é RELIDO do disco, e cada status só entra se a linha ainda tiver
    o mesmo pedido/processo lidos no início (evita escrever na linha errada se alguém inseriu ou
    apagou linhas durante a execução) e se a célula de status não foi editada à mão nesse meio-tempo;
  * a gravação é atômica (arquivo temporário + replace) e há backup antes da primeira gravação.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

from models.item import CONCLUIDO, ERRO, IGNORADO, PENDENTE, ItemControle
from src.erros import PlanilhaError
from src.planilha.estado import EstadoCsv

COL_PEDIDO, COL_PROCESSO = "pedido_sap", "processo"
COL_STATUS, COL_DATA, COL_OBS = "status", "data_processamento", "observacao"
COL_FILTRO = "filtro"  # coluna da base que diz se o processo precisa (ou não) de COA

# Como cada status aparece escrito na planilha
ROTULOS = {CONCLUIDO: "JÁ ANEXADO", ERRO: "ERRO", IGNORADO: "IGNORADO"}
_SINONIMOS = {
    "JA ANEXADO": CONCLUIDO, "JA ANEXADA": CONCLUIDO, "ANEXADO": CONCLUIDO,
    "ANEXADA": CONCLUIDO, "CONCLUIDO": CONCLUIDO, "CONCLUIDA": CONCLUIDO,
    "ERRO": ERRO, "IGNORADO": IGNORADO, "PENDENTE": PENDENTE,
}
STATUS_CONHECIDOS = {"", PENDENTE, CONCLUIDO, ERRO, IGNORADO}

# Nomes alternativos aceitos no cabeçalho (comparação sem caixa/espaços extras)
_ALIASES = {
    COL_PEDIDO: {"pedido_sap", "pedido sap", "pedido", "numero_pedido", "n_pedido", "nº pedido", "po", "ebeln"},
    COL_PROCESSO: {"processo", "numero_processo", "n_processo", "nº processo", "n_do_processo"},
    COL_STATUS: {"status", "situacao", "situação"},
    COL_DATA: {"data_processamento", "data processamento", "processado_em"},
    COL_OBS: {"observacao", "observação", "obs", "mensagem"},
}


def _norm_cab(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().lower()


def _texto(v) -> str:
    """Converte célula em texto limpo (4500001001.0 -> '4500001001')."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def status_de_texto(valor) -> str:
    """Texto da célula -> código interno. Texto desconhecido volta normalizado (e é pulado)."""
    t = unicodedata.normalize("NFKD", _texto(valor))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\s+", " ", t).strip().upper()
    return _SINONIMOS.get(t, t)


class PlanilhaControle:
    def __init__(self, caminho: Path, aba: str | None = None, log=None, *,
                 col_pedido: str | None = None, col_processo: str | None = None,
                 col_status: str | None = None, col_obs: str | None = None,
                 col_data: str | None = None, col_filtro: str | None = None,
                 linha_cabecalho: int = 1,
                 gravar_na_planilha: bool = True, arquivo_estado: Path | None = None,
                 pasta_backup: Path | None = None, ignorar_estado: bool = False):
        """col_*: letra ("I") ou nome do cabeçalho; None = procura por apelidos conhecidos.
        Se col_status NÃO for informado (modo legado), colunas status/data/observacao que não
        existirem são criadas no fim do cabeçalho. Se for informado, só as colunas informadas
        são escritas e a de status precisa ter cabeçalho (você cria a coluna, o robô não adivinha).
        gravar_na_planilha=False -> planilha só lida; andamento em `arquivo_estado` (CSV).
        gravar_na_planilha=True + arquivo_estado -> o CSV é a MEMÓRIA do robô e a coluna de status
        da planilha é um ESPELHO dele: se a base for substituída por uma cópia nova (sem status), o
        robô repõe o status dos pedidos já concluídos sem reabrir o SAP.
        ignorar_estado=True -> ignora status da planilha e do CSV (para forçar reprocessamento)."""
        self.caminho = Path(caminho)
        self.aba = aba
        self.log = log
        self.col_pedido, self.col_processo = col_pedido, col_processo
        self.col_status, self.col_obs, self.col_data = col_status, col_obs, col_data
        self.col_filtro = col_filtro
        self.linha_cabecalho = linha_cabecalho
        self.gravar_na_planilha = gravar_na_planilha
        self.pasta_backup = Path(pasta_backup) if pasta_backup else None
        self.ignorar_estado = ignorar_estado
        self._estado: EstadoCsv | None = None
        if not gravar_na_planilha and arquivo_estado is None:
            raise ValueError("arquivo_estado é obrigatório quando gravar_na_planilha=False")
        if arquivo_estado is not None:
            self._estado = EstadoCsv(arquivo_estado, log)
        self._ws = None                      # aba com VALORES (data_only)
        self._nome_aba: str | None = None
        self._cols: dict[str, int] = {}
        self._cabecalhos_novos: dict[int, str] = {}
        self._pendentes: dict[int, tuple[ItemControle, str, str, str]] = {}
        self._backup_feito = False
        self._proxima_coluna_nova: int | None = None
        self.conflitos: list[str] = []       # linhas cujo status NÃO foi gravado (e por quê)

    # ------------------------------------------------------------------ leitura
    def carregar(self) -> list[ItemControle]:
        if not self.caminho.exists():
            raise PlanilhaError(f"Planilha de controle não encontrada: {self.caminho}")
        try:
            wb = self._abrir_para_leitura()
        except Exception as e:
            raise PlanilhaError(f"Não consegui abrir a planilha ({e})") from e

        if self.aba and self.aba not in wb.sheetnames:
            raise PlanilhaError(f"Aba '{self.aba}' não existe. Abas: {wb.sheetnames}")
        self._ws = wb[self.aba] if self.aba else wb.worksheets[0]
        self._nome_aba = self._ws.title

        self._mapear_colunas()
        itens = []
        for linha in range(self.linha_cabecalho + 1, self._ws.max_row + 1):
            pedido = _texto(self._ws.cell(linha, self._cols[COL_PEDIDO]).value)
            processo = _texto(self._ws.cell(linha, self._cols[COL_PROCESSO]).value)
            if not pedido and not processo:
                continue  # linha totalmente vazia
            reg = (self._estado.obter_registro(pedido, processo)
                   if self._estado and not self.ignorar_estado else None)
            espelhar = None
            if self.gravar_na_planilha:
                status = (status_de_texto(self._ws.cell(linha, self._cols[COL_STATUS]).value)
                          if COL_STATUS in self._cols else "")
                obs = (_texto(self._ws.cell(linha, self._cols[COL_OBS]).value)
                       if COL_OBS in self._cols else "")
                if not status and reg and status_de_texto(reg.get("status")) in (CONCLUIDO, ERRO):
                    # base nova/limpa, mas o robô já tratou este pedido: repõe o status na planilha
                    status, obs = status_de_texto(reg["status"]), reg.get("observacao", "")
                    espelhar = reg.get("data_processamento") or None
            else:
                status, obs = (reg["status"].upper(), reg.get("observacao", "")) if reg else ("", "")
            if self.ignorar_estado:  # --forcar: status da planilha e do CSV não valem; refaz
                status, obs, espelhar = "", "", None
            criterio = (_texto(self._ws.cell(linha, self._cols[COL_FILTRO]).value)
                        if COL_FILTRO in self._cols else "")
            itens.append(ItemControle(linha=linha, pedido=pedido, processo=processo,
                                      status=status, observacao=obs, criterio=criterio))
            if espelhar is not None:
                self._pendentes[linha] = (itens[-1], status, obs[:500], espelhar)
        self._validar(itens)
        self._herdar_status_nas_duplicatas(itens)
        self._conferir_coluna_status(itens)
        return itens

    def _herdar_status_nas_duplicatas(self, itens: list[ItemControle]) -> None:
        """A base vem do Power BI com uma linha por material: o mesmo pedido se repete. Linha
        duplicada mostra o mesmo status da linha original (quando esta já está concluída/com erro)."""
        originais = {(i.pedido, i.processo): i for i in reversed(itens)
                     if not i.duplicado and i.pedido and i.processo}
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for it in itens:
            if not it.duplicado or it.status:
                continue
            o = originais.get((it.pedido, it.processo))
            if o and o.status in (CONCLUIDO, ERRO):
                it.status, it.observacao = o.status, o.observacao
                if self.gravar_na_planilha:
                    self._pendentes[it.linha] = (it, o.status, o.observacao[:500], agora)

    def _abrir_para_leitura(self):
        """Modo só-leitura (base do sistema no SharePoint): lê de uma CÓPIA local temporária.
        Assim o robô enxerga um retrato consistente do arquivo, força o OneDrive a baixá-lo por
        inteiro e não segura o arquivo original aberto. O original nunca é alterado."""
        if self.gravar_na_planilha:
            return load_workbook(self.caminho, data_only=True)
        ultimo = None
        for n in range(1, 4):
            with tempfile.TemporaryDirectory(prefix="coa_base_") as tmp:
                copia = Path(tmp) / self.caminho.name
                try:
                    shutil.copyfile(self.caminho, copia)
                    return load_workbook(copia, data_only=True)
                except PermissionError as e:  # sincronizando / aberta de forma exclusiva
                    ultimo = e
                    if self.log:
                        self.log.warning("Base em uso (tentativa %d/3): %s", n, e)
            time.sleep(1)
        raise ultimo  # type: ignore[misc]

    def _conferir_coluna_status(self, itens: list[ItemControle]) -> None:
        """Protege contra apontar o status para uma coluna que já tem outro conteúdo
        (ex.: uma coluna de datas): nesse caso a maioria das linhas teria 'status' desconhecido."""
        if not (self.gravar_na_planilha and self.col_status and COL_STATUS in self._cols):
            return
        estranhos = [i for i in itens if i.status not in STATUS_CONHECIDOS]
        if len(estranhos) >= 5 and len(estranhos) > len(itens) / 2:
            col = self._cols[COL_STATUS]
            letra = self._ws.cell(1, col).column_letter
            titulo = self._ws.cell(self.linha_cabecalho, col).value
            exemplos = ", ".join(repr(i.status[:25]) for i in estranhos[:3])
            raise PlanilhaError(
                f"A coluna {letra} (cabeçalho {titulo!r}) parece ter outro conteúdo: "
                f"{len(estranhos)} de {len(itens)} linhas têm valores que não são status "
                f"(ex.: {exemplos}). Use uma coluna livre, nova, com título próprio "
                f"(defina COA_COL_STATUS).")

    def _ultima_coluna_com_titulo(self) -> int:
        """Última coluna que realmente tem título (ex.: CL). Não usa max_column: o Excel guarda
        formatação em colunas vazias à direita, e a coluna nova ficaria longe da tabela."""
        return max((c.column for c in self._ws[self.linha_cabecalho] if c.value not in (None, "")),
                   default=0)

    def _mapear_colunas(self) -> None:
        cab = {_norm_cab(c.value): c.column
               for c in self._ws[self.linha_cabecalho] if c.value is not None}
        vistos: dict[str, int] = {}
        self._cab_repetidos: set[str] = set()
        for c in self._ws[self.linha_cabecalho]:
            if c.value is not None:
                n = _norm_cab(c.value)
                vistos[n] = vistos.get(n, 0) + 1
                if vistos[n] == 2:
                    self._cab_repetidos.add(n)
        saidas = (COL_STATUS, COL_OBS, COL_DATA)
        explicitas = {COL_PEDIDO: self.col_pedido, COL_PROCESSO: self.col_processo,
                      COL_STATUS: self.col_status, COL_OBS: self.col_obs, COL_DATA: self.col_data}
        for canon, espec in explicitas.items():
            if not (espec and (canon not in saidas or self.gravar_na_planilha)):
                continue
            try:
                self._cols[canon] = self._resolver_coluna(str(espec), cab, self._cab_repetidos)
            except PlanilhaError:
                if canon not in saidas or re.fullmatch(r"[A-Za-z]{1,3}", str(espec).strip()):
                    raise  # entrada, ou letra de coluna: não inventa
                # coluna de SAÍDA pelo NOME e ela não existe (ex.: cópia nova da base): cria no fim
                if self._proxima_coluna_nova is None:
                    self._proxima_coluna_nova = self._ultima_coluna_com_titulo() + 1
                self._cols[canon] = self._proxima_coluna_nova
                self._cabecalhos_novos[self._proxima_coluna_nova] = str(espec).strip()
                self._proxima_coluna_nova += 1

        modo_explicito = self.gravar_na_planilha and bool(self.col_status)
        for canon, apelidos in _ALIASES.items():
            if canon in self._cols:
                continue
            if canon in saidas and (not self.gravar_na_planilha or modo_explicito):
                continue  # no modo explícito o robô não adivinha colunas de saída
            achada = next((cab[a] for a in apelidos if a in cab), None)
            if achada:
                self._cols[canon] = achada

        if self.col_filtro:  # coluna de ENTRADA (só lida), sempre informada pelo usuário
            self._cols[COL_FILTRO] = self._resolver_coluna(str(self.col_filtro), cab,
                                                           self._cab_repetidos)

        faltando = [c for c in (COL_PEDIDO, COL_PROCESSO) if c not in self._cols]
        if faltando:
            raise PlanilhaError(
                f"Colunas obrigatórias ausentes: {faltando}. Cabeçalho (linha "
                f"{self.linha_cabecalho}) encontrado: {list(cab)}")

        if modo_explicito:  # a coluna de saída tem que existir e ter título (você a cria)
            for canon in saidas:
                if canon in self._cols and self._cols[canon] not in self._cabecalhos_novos:
                    titulo = self._ws.cell(self.linha_cabecalho, self._cols[canon]).value
                    if titulo in (None, ""):
                        letra = self._ws.cell(1, self._cols[canon]).column_letter
                        raise PlanilhaError(
                            f"A coluna {letra} ({canon}) não tem título na linha "
                            f"{self.linha_cabecalho}. Crie a coluna na planilha, dê um título "
                            f"(ex.: STATUS) e rode de novo.")
        elif self.gravar_na_planilha:  # legado: cria o que faltar no fim do cabeçalho
            proxima = self._ultima_coluna_com_titulo() + 1
            for canon in (COL_STATUS, COL_DATA, COL_OBS):
                if canon not in self._cols:
                    self._cols[canon] = proxima
                    self._cabecalhos_novos[proxima] = canon
                    proxima += 1

        if self.log:
            for canon in (COL_PEDIDO, COL_PROCESSO, COL_FILTRO, *saidas):
                if canon in self._cols and self._cols[canon] not in self._cabecalhos_novos:
                    col = self._cols[canon]
                    self.log.info("Coluna %s: %s (cabeçalho: %r)", canon,
                                  self._ws.cell(1, col).column_letter,
                                  self._ws.cell(self.linha_cabecalho, col).value)

    @staticmethod
    def _resolver_coluna(espec: str, cab: dict[str, int], repetidos=frozenset()) -> int:
        espec = espec.strip()
        if re.fullmatch(r"[A-Za-z]{1,3}", espec):  # letra de coluna: "G", "H", "AB"
            return column_index_from_string(espec.upper())
        if _norm_cab(espec) in repetidos:
            raise PlanilhaError(
                f"O cabeçalho '{espec}' aparece em mais de uma coluna; não sei qual usar. "
                f"Indique a coluna pela letra (ex.: COA_COL_PEDIDO=H).")
        achada = cab.get(_norm_cab(espec))
        if achada is None:
            raise PlanilhaError(f"Coluna '{espec}' não encontrada no cabeçalho: {list(cab)}")
        return achada

    @staticmethod
    def _validar(itens: list[ItemControle]) -> None:
        """Marca linhas inválidas (erro_validacao) sem derrubar a execução."""
        por_pedido: dict[str, list[ItemControle]] = defaultdict(list)
        for it in itens:
            if not it.pedido:
                it.erro_validacao = "pedido vazio"
            elif not it.pedido.isdigit():
                it.erro_validacao = f"pedido '{it.pedido}' não é numérico"
            elif not it.processo:
                it.erro_validacao = "número do processo vazio"
            else:
                por_pedido[it.pedido].append(it)

        for pedido, lista in por_pedido.items():
            if len(lista) == 1:
                continue
            processos = {i.processo for i in lista}
            if len(processos) > 1:
                for i in lista:
                    i.erro_validacao = (f"pedido {pedido} aparece com processos diferentes: "
                                        f"{sorted(processos)}")
            else:  # duplicata exata: processa a primeira, ignora as demais
                for dup in lista[1:]:
                    dup.duplicado = True
                    dup.erro_validacao = f"duplicata da linha {lista[0].linha}"

    # ------------------------------------------------------------------ escrita
    def atualizar(self, item: ItemControle, status: str, observacao: str = "") -> None:
        if not self.gravar_na_planilha:
            if not item.duplicado:  # duplicata compartilha a chave da original: não sobrescrever
                self._estado.registrar(item.pedido, item.processo, status, observacao)
            item.status, item.observacao = status, observacao
            return
        quando = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self._estado and not item.duplicado:  # CSV = memória do robô; a planilha é o espelho
            self._estado.registrar(item.pedido, item.processo, status, observacao)
        self._pendentes[item.linha] = (item, status, observacao[:500], quando)
        item.status, item.observacao = status, observacao

    def salvar(self, tentativas: int = 3) -> bool:
        """Persiste o andamento. Nunca levanta exceção por falha de gravação: devolve False e
        mantém tudo pendente (o relatório CSV da execução garante o registro)."""
        csv_ok = self._estado.salvar() if self._estado else True
        if not self.gravar_na_planilha:
            return csv_ok
        return self._salvar_planilha(tentativas) and csv_ok

    def _salvar_planilha(self, tentativas: int) -> bool:
        if not self._pendentes and not self._cabecalhos_novos:
            return True
        for n in range(1, tentativas + 1):
            try:
                self._gravar_na_planilha()
                return True
            except PermissionError:
                if self.log:
                    self.log.warning("Planilha aberta em outro programa; tentativa %d/%d de salvar",
                                     n, tentativas)
                time.sleep(1)
            except Exception as e:
                if self.log:
                    self.log.error("Falha ao gravar na planilha (%s: %s); status seguem pendentes",
                                   type(e).__name__, e)
                return False
        return False

    def _gravar_na_planilha(self) -> None:
        xlsm = self.caminho.suffix.lower() == ".xlsm"
        wb = load_workbook(self.caminho, keep_vba=xlsm)                    # para gravar
        wsv = load_workbook(self.caminho, data_only=True)[self._nome_aba]  # para conferir valores
        ws = wb[self._nome_aba]
        cab = self.linha_cabecalho

        for col, titulo in self._cabecalhos_novos.items():
            if ws.cell(cab, col).value in (None, ""):
                ws.cell(cab, col, titulo)

        resolvidas, conflitos_novos = [], []
        for linha, (item, status, obs, quando) in self._pendentes.items():
            ped = _texto(wsv.cell(linha, self._cols[COL_PEDIDO]).value)
            proc = _texto(wsv.cell(linha, self._cols[COL_PROCESSO]).value)
            if (ped, proc) != (item.pedido, item.processo):
                conflitos_novos.append(
                    f"linha {linha} mudou na planilha desde a leitura (lido: pedido {item.pedido}/"
                    f"processo {item.processo}; agora: {ped}/{proc}) — status '{status}' NÃO gravado")
            elif status_de_texto(wsv.cell(linha, self._cols[COL_STATUS]).value) not in STATUS_CONHECIDOS:
                conflitos_novos.append(
                    f"linha {linha} (pedido {item.pedido}) recebeu um status manual durante a "
                    f"execução — status '{status}' NÃO gravado")
            else:
                ws.cell(linha, self._cols[COL_STATUS], ROTULOS.get(status, status))
                if COL_DATA in self._cols:
                    ws.cell(linha, self._cols[COL_DATA], quando)
                if COL_OBS in self._cols:
                    ws.cell(linha, self._cols[COL_OBS], obs)
            resolvidas.append(linha)

        self._fazer_backup_uma_vez()
        # grava num temporário ao lado e troca: queda no meio não corrompe a base compartilhada.
        # Se o arquivo estiver aberto no Excel, o replace levanta PermissionError (tratado acima).
        tmp = self.caminho.with_name(self.caminho.stem + ".robo.tmp")
        try:
            with open(tmp, "wb") as f:
                wb.save(f)
            os.replace(tmp, self.caminho)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

        for linha in resolvidas:
            del self._pendentes[linha]
        self._cabecalhos_novos.clear()
        for c in conflitos_novos:
            self.conflitos.append(c)
            if self.log:
                self.log.error("%s", c)

    def _fazer_backup_uma_vez(self) -> None:
        if self._backup_feito or not self.pasta_backup:
            return
        self.pasta_backup.mkdir(parents=True, exist_ok=True)
        destino = self.pasta_backup / (
            f"{self.caminho.stem}_{datetime.now():%Y%m%d_%H%M%S}{self.caminho.suffix}")
        shutil.copy2(self.caminho, destino)
        self._backup_feito = True
        if self.log:
            self.log.info("Backup da planilha antes da 1ª gravação: %s", destino)
