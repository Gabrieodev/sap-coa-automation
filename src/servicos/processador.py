"""Loop principal: para cada pedido da planilha, anexa os arquivos do processo no SAP.

Política de erros
-----------------
* ErroDeItem   -> marca ERRO naquela linha, registra o motivo e SEGUE para o próximo.
* ErroFatal    -> (SAP caiu/deslogou) interrompe tudo; o que faltou continua PENDENTE.
* Exceção inesperada -> trata como ERRO do item (com traceback no log).
* Disjuntor: N falhas "técnicas" seguidas (seletor errado, diálogo travado, bug) abortam a
  execução, para não rodar centenas de pedidos com o mesmo defeito.

Idempotência
------------
Antes de anexar, lista os anexos que o pedido já tem e só envia o que falta; depois confere
que cada arquivo apareceu na lista. Rodar duas vezes não duplica anexo.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from models.item import CONCLUIDO, DRY_RUN, ERRO, IGNORADO, ItemControle, Resultado
from src.erros import (AnexoNaoConfirmadoError, ErroDeItem, ErroFatal, DadosInvalidosError,
                       AnexoFalhouError)
from src.planilha.controle import STATUS_CONHECIDOS
from src.utils.nomes import chave_anexo


@dataclass
class ResumoExecucao:
    resultados: list[Resultado]
    abortado: bool = False
    motivo_aborto: str = ""

    def contagem(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for r in self.resultados:
            c[r.status] = c.get(r.status, 0) + 1
        return c


class Processador:
    def __init__(self, cfg, planilha, provedor, sap, log, dry_run: bool = False):
        self.cfg, self.planilha, self.provedor = cfg, planilha, provedor
        self.sap, self.log, self.dry_run = sap, log, dry_run
        self._desde_ultimo_save = 0

    # ------------------------------------------------------------------ público
    def executar(self, limite: int | None = None, reprocessar_erros: bool = False,
                 linhas: tuple[int | None, int | None] | None = None,
                 pedidos: set[str] | None = None) -> ResumoExecucao:
        """linhas=(inicio, fim) inclusivos (None = sem limite); pedidos = só estes pedidos.
        Úteis para começar por um trecho pequeno de uma base grande e antiga."""
        itens = self.planilha.carregar()
        desconhecidos = [i for i in itens if i.status.upper() not in STATUS_CONHECIDOS]
        if desconhecidos:  # texto escrito à mão (ex.: "SEM COA"): respeitado, linha pulada
            self.log.warning("%d linha(s) com status não reconhecido foram PULADAS (ex.: %s)",
                             len(desconhecidos),
                             ", ".join(f"linha {i.linha}='{i.status}'" for i in desconhecidos[:5]))
        fila = [i for i in itens if i.deve_processar(reprocessar_erros)]
        if linhas:
            ini, fim = linhas
            fila = [i for i in fila if (ini is None or i.linha >= ini) and (fim is None or i.linha <= fim)]
        if pedidos:
            fila = [i for i in fila if i.pedido in pedidos]
        if limite:
            fila = fila[:limite]
        self.log.info("Planilha: %d linhas | a processar: %d | dry-run: %s",
                      len(itens), len(fila), self.dry_run)

        resumo = ResumoExecucao(resultados=[])
        self._desde_ultimo_save = 0
        try:
            self._percorrer(fila, resumo)
        except KeyboardInterrupt:  # Ctrl+C: encerra de forma limpa (salva e gera o relatório)
            resumo.abortado, resumo.motivo_aborto = True, "Interrompido pelo usuário (Ctrl+C)"
            self.log.warning("Interrompido pelo usuário; o pedido em andamento NÃO foi registrado")
        finally:
            # roda também com exceção não prevista: o que já foi feito não se perde
            if not self.planilha.salvar():
                self.log.warning("Não consegui salvar a planilha (aberta no Excel?). "
                                 "Os resultados estão no relatório CSV.")
        return resumo

    def _percorrer(self, fila: list[ItemControle], resumo: ResumoExecucao) -> None:
        tecnicos_seguidos = 0
        for n, item in enumerate(fila, start=1):
            self.log.info("[%d/%d] linha %d | pedido %s | processo %s",
                          n, len(fila), item.linha, item.pedido, item.processo)
            inicio = time.monotonic()
            try:
                res = self._processar_item(item)
                tecnicos_seguidos = 0
            except ErroFatal as e:
                self.log.critical("ERRO FATAL, abortando execução: %s", e)
                resumo.abortado, resumo.motivo_aborto = True, str(e)
                return
            except ErroDeItem as e:
                self.log.error("  ✗ %s", e)
                res = Resultado(item, ERRO, str(e))
                tecnicos_seguidos = tecnicos_seguidos + 1 if e.tecnico else 0
                self._recuperar()
            except Exception as e:  # bug ou situação não prevista
                self.log.exception("  ✗ erro inesperado no pedido %s", item.pedido)
                res = Resultado(item, ERRO, f"Erro inesperado: {type(e).__name__}: {e}")
                tecnicos_seguidos += 1
                self._recuperar()

            res.duracao_s = time.monotonic() - inicio
            self._registrar(res)
            resumo.resultados.append(res)

            if tecnicos_seguidos >= self.cfg.max_erros_inesperados_seguidos:
                resumo.abortado = True
                resumo.motivo_aborto = (f"{tecnicos_seguidos} falhas técnicas seguidas — "
                                        "provável problema de seletor/ambiente")
                self.log.critical("Disjuntor acionado: %s", resumo.motivo_aborto)
                return

    # ------------------------------------------------------------------ interno
    def _processar_item(self, item: ItemControle) -> Resultado:
        if item.duplicado:
            return Resultado(item, IGNORADO, item.erro_validacao or "linha duplicada")
        if item.erro_validacao:
            raise DadosInvalidosError(item.erro_validacao)

        # 1) arquivos primeiro: se a pasta está errada, nem encosta no SAP
        arquivos = self.provedor.obter_arquivos(item.processo)

        # 2) pedido no SAP + o que já está anexado
        self.sap.abrir_pedido(item.pedido)
        existentes = {chave_anexo(n) for n in self.sap.listar_anexos()}
        novos = [a for a in arquivos if chave_anexo(a.name) not in existentes]
        ja_tinha = [a.name for a in arquivos if chave_anexo(a.name) in existentes]

        if not novos:
            return Resultado(item, CONCLUIDO, "Todos os arquivos já estavam anexados",
                             ja_existiam=ja_tinha)
        if self.dry_run:
            return Resultado(item, DRY_RUN, f"Anexaria {len(novos)} arquivo(s)",
                             anexados=[a.name for a in novos], ja_existiam=ja_tinha)

        # 3) anexa um a um; em falha parcial o relatório diz o que entrou e o que não
        feitos: list[str] = []
        for arq in novos:
            try:
                self._anexar_com_retentativa(arq)
                feitos.append(arq.name)
            except ErroDeItem as e:
                e.args = (f"{e} | já anexados: {feitos or 'nenhum'} | falhou: {arq.name}",)
                raise

        # 4) confere que cada arquivo apareceu na lista de anexos do pedido
        confirmados = {chave_anexo(n) for n in self.sap.listar_anexos()}
        faltando = [a.name for a in novos if chave_anexo(a.name) not in confirmados]
        if faltando:
            raise AnexoNaoConfirmadoError(f"Enviado, mas não consta na lista de anexos: {faltando}")

        msg = f"{len(feitos)} arquivo(s) anexado(s)"
        if ja_tinha:
            msg += f" ({len(ja_tinha)} já estava(m) anexado(s))"
        return Resultado(item, CONCLUIDO, msg, anexados=feitos, ja_existiam=ja_tinha)

    def _anexar_com_retentativa(self, arquivo) -> None:
        total = max(self.cfg.tentativas_anexo, 1)
        for tentativa in range(1, total + 1):
            try:
                self.sap.anexar(arquivo)
                return
            except AnexoFalhouError as e:
                self.log.warning("  anexo '%s' falhou (tentativa %d/%d): %s",
                                 arquivo.name, tentativa, total, e)
                if tentativa == total:
                    raise
                self.sap.limpar_popups()
                time.sleep(1)

    def _registrar(self, res: Resultado) -> None:
        if res.status == CONCLUIDO:
            self.log.info("  ✓ %s", res.mensagem)
        elif res.status == DRY_RUN:
            self.log.info("  ~ [dry-run] %s: %s", res.mensagem, res.anexados)
        elif res.status == IGNORADO:
            self.log.info("  - ignorado: %s", res.mensagem)
        if self.dry_run:
            return  # dry-run nunca escreve na planilha
        self.planilha.atualizar(res.item, res.status, res.mensagem)
        self._desde_ultimo_save += 1
        if self._desde_ultimo_save >= max(int(self.cfg.salvar_a_cada), 1):
            self.planilha.salvar()  # a cada N itens; o salvamento final fica no `finally`
            self._desde_ultimo_save = 0

    def _recuperar(self) -> None:
        """Deixa o SAP em tela limpa para o próximo pedido."""
        try:
            self.sap.limpar_popups()
        except Exception as e:
            self.log.debug("limpar_popups falhou: %s", e)
