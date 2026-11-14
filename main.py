"""Robô de anexo de COA (comex) no SAP.

Exemplos:
  python main.py --simulado                 # roda tudo sem SAP, com a base fictícia
  python main.py --teste-conexao            # só abre a ME22N (o que o main antigo fazia)
  python main.py --dry-run --limite 3       # SAP real, mas NÃO anexa nada
  python main.py                            # execução real
  python main.py --reprocessar-erros        # tenta de novo as linhas com status ERRO
  python main.py --linhas 2-50              # só as linhas 2 a 50 da planilha (use "100-" p/ "da 100 em diante")
  python main.py --pedidos 4500001001 4500001002

Códigos de saída: 0 = tudo certo | 1 = houve itens com erro | 2 = execução abortada |
3 = já há outra execução do robô em andamento
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import config as cfg_mod
from src.arquivos.provedor import PastaSincronizada
from src.ambiente import resolver_planilha, resolver_raiz_arquivos
from src.erros import ErroFatal
from src.planilha.controle import PlanilhaControle
from src.servicos.processador import Processador
from src.utils.console import usar_utf8
from src.utils.logger import configurar_logger, encerrar_logger, gravar_relatorio_csv
from src.utils.trava import ExecucaoEmAndamentoError, TravaExecucao


def _intervalo(texto: str):
    """'2-50' -> (2, 50) | '100-' -> (100, None) | '-50' -> (None, 50) | '7' -> (7, 7)"""
    ini, sep, fim = texto.partition("-")
    try:
        if not sep:
            return int(ini), int(ini)
        return (int(ini) if ini else None), (int(fim) if fim else None)
    except ValueError:
        raise argparse.ArgumentTypeError(f"intervalo inválido: {texto!r} (use ex.: 2-50)")


def _args():
    p = argparse.ArgumentParser(description="Anexa COA de comex nos pedidos do SAP.")
    p.add_argument("--simulado", action="store_true", help="usa SAP simulado (sem SAP GUI)")
    p.add_argument("--dry-run", action="store_true", help="não anexa nem altera a planilha")
    p.add_argument("--teste-conexao", action="store_true", help="apenas abre a transação no SAP")
    p.add_argument("--limite", type=int, help="processa no máximo N pedidos")
    p.add_argument("--reprocessar-erros", action="store_true")
    p.add_argument("--forcar", action="store_true",
                   help="refaz mesmo o que já consta como feito (exige --pedidos ou --linhas)")
    p.add_argument("--linhas", type=_intervalo, help='intervalo de linhas da planilha, ex.: "2-50"')
    p.add_argument("--pedidos", nargs="+", help="processa só estes números de pedido")
    p.add_argument("--planilha", type=Path, help="caminho da planilha de controle")
    p.add_argument("--pasta-arquivos", type=Path, help="raiz das pastas dos processos")
    return p.parse_args()


def _conectar_sap_real(cfg, log):
    from src.sap.dialogo_arquivo import DialogoArquivo
    from src.sap.navegacao import SapNavigation
    from src.sap.pedidos import SapPedidos
    nav = SapNavigation()  # levanta SapNaoAbertoError / SapNaoLogadoError se for o caso
    dialogo = DialogoArquivo(cfg.timeout_dialogo_arquivo, espera_seguranca=cfg.espera_janela_seguranca)
    return SapPedidos(nav, dialogo, cfg.transacao,
                      cfg.timeout_sap, cfg.coluna_titulo_anexos, log)


def _sap_real(cfg, log):
    """SAP real, mas só conecta quando algum pedido realmente precisar (ver preguicoso.py)."""
    from src.sap.preguicoso import SapPreguicoso
    return SapPreguicoso(lambda: _conectar_sap_real(cfg, log), log)


def _sap_simulado():
    """Cenários coerentes com a base fictícia (scripts/gerar_base_ficticia.py)."""
    from src.sap.simulado import SapSimulado
    return SapSimulado(
        inexistentes={"4500001006"},
        bloqueados={"4500001007"},
        anexos_iniciais={"4500001003": ["COA_0003-26_lote1"]},
    )


def main() -> int:
    usar_utf8()  # ✓ e → no log não podem derrubar a saída redirecionada do Windows (cp1252)
    try:
        return _executar()
    finally:
        # solta o arquivo de log: no Windows, arquivo aberto não pode ser apagado nem movido
        for nome, lg in list(logging.root.manager.loggerDict.items()):
            if nome.startswith("coa.") and isinstance(lg, logging.Logger):
                encerrar_logger(lg)


def _executar() -> int:
    args = _args()
    cfg = cfg_mod.carregar()
    if args.planilha:
        cfg.planilha = args.planilha
    if args.pasta_arquivos:
        cfg.raiz_arquivos = args.pasta_arquivos
    if args.simulado:  # dados FICTÍCIOS só aqui; sem --simulado o robô usa tudo REAL
        if cfg.planilha is None:           # nada informado: demonstração completa
            cfg.planilha = cfg_mod.PLANILHA_DEMO
            cfg.raiz_arquivos = cfg.raiz_arquivos or cfg_mod.RAIZ_DEMO
        # base informada (COA_PLANILHA/--planilha) e documentos não: os documentos reais são achados abaixo

    if args.forcar and not (args.pedidos or args.linhas):
        print("--forcar refaz o que já foi feito: informe --pedidos ou --linhas para limitar.")
        return 2

    if args.teste_conexao:
        try:
            from src.sap.navegacao import SapNavigation
            SapNavigation().abrir_transacao(cfg.transacao)
        except ErroFatal as e:
            print(f"Falha na conexão: {e}")
            return 2
        print(f"Transação {cfg.transacao} aberta com sucesso.")
        return 0

    log, ts = configurar_logger(cfg.logs_dir)
    trava = TravaExecucao(cfg.arquivo_estado.parent / "robo.lock", cfg.trava_validade_horas)
    try:
        trava.adquirir()
    except ExecucaoEmAndamentoError as e:
        log.error("%s", e)
        return 3
    try:
        return _rodar(args, cfg, log, ts)
    finally:
        trava.liberar()


def _rodar(args, cfg, log, ts) -> int:
    try:
        cfg.planilha = resolver_planilha(cfg)
        cfg.raiz_arquivos = resolver_raiz_arquivos(cfg)
        if (args.simulado and not args.dry_run
                and Path(cfg.planilha).resolve() != cfg_mod.PLANILHA_DEMO.resolve()
                and not os.environ.get("COA_PERMITIR_SIMULADO_NA_BASE")):
            # SAP de mentirinha + base real = "JÁ ANEXADO" falso na base e no CSV: o robô nunca
            # mais anexaria esses pedidos. Para testar com a base real, use --dry-run.
            log.error("--simulado não grava na base real (%s). Use --dry-run para testar com ela, "
                      "ou rode a demonstração (python main.py --simulado, sem COA_PLANILHA).",
                      cfg.planilha)
            return 2
        log.info("Iniciando | modo: %s | dry-run: %s",
                 "SIMULADO (dados fictícios)" if args.simulado else "REAL (SAP, SharePoint, base e "
                 "documentos reais)", args.dry_run)
        log.info("Base de controle: %s (processo=%r, pedido=%r)", cfg.planilha, cfg.col_processo,
                 cfg.col_pedido)
        log.info("Documentos dos processos: %s", cfg.raiz_arquivos)
        log.info("Status gravado na coluna %r da base (memória do robô: %s)",
                 cfg.col_status, cfg.arquivo_estado)
        sap = _sap_simulado() if args.simulado else _sap_real(cfg, log)
        planilha = PlanilhaControle(
            cfg.planilha, cfg.aba, log, col_pedido=cfg.col_pedido, col_processo=cfg.col_processo,
            col_status=cfg.col_status, col_obs=cfg.col_obs, col_data=cfg.col_data,
            col_filtro=cfg.col_filtro, linha_cabecalho=cfg.linha_cabecalho, gravar_na_planilha=cfg.gravar_status_na_planilha,
            arquivo_estado=cfg.arquivo_estado, ignorar_estado=args.forcar,
            pasta_backup=cfg.logs_dir / "backup_planilha" if cfg.backup_planilha else None)
        provedor = PastaSincronizada(cfg.raiz_arquivos, cfg.extensoes_permitidas, log=log,
                                     profundidade=cfg.profundidade_busca,
                                     buscar_por_prefixo=cfg.buscar_pasta_por_prefixo)
        proc = Processador(cfg, planilha, provedor, sap, log, dry_run=args.dry_run)
        resumo = proc.executar(limite=args.limite, reprocessar_erros=args.reprocessar_erros,
                               linhas=args.linhas, pedidos=set(args.pedidos or ()) or None)
    except ErroFatal as e:
        log.critical("Execução não pôde começar/continuar: %s", e)
        return 2

    log.info("Pastas listadas no SharePoint (plano B de busca por prefixo): %d", provedor.listagens)
    relatorio = gravar_relatorio_csv(cfg.logs_dir, ts, resumo.resultados)
    log.info("Resumo: %s | relatório: %s", resumo.contagem(), relatorio)
    if resumo.abortado:
        log.critical("Execução ABORTADA: %s", resumo.motivo_aborto)
        return 2
    return 1 if resumo.contagem().get("ERRO") else 0


if __name__ == "__main__":
    sys.exit(main())
