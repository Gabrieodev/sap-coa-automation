"""Robô de anexo de COA (comex) no SAP.

Exemplos:
  python main.py --simulado                 # roda tudo sem SAP, com a base fictícia
  python main.py --teste-conexao            # só abre a ME23N (o que o main antigo fazia)
  python main.py --dry-run --limite 3       # SAP real, mas NÃO anexa nada
  python main.py                            # execução real
  python main.py --reprocessar-erros        # tenta de novo as linhas com status ERRO
  python main.py --linhas 2-50              # só as linhas 2 a 50 da planilha (use "100-" p/ "da 100 em diante")
  python main.py --pedidos 4500001001 4500001002

Códigos de saída: 0 = tudo certo | 1 = houve itens com erro | 2 = execução abortada
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import config as cfg_mod
from src.arquivos.provedor import PastaSincronizada
from src.erros import ErroFatal
from src.planilha.controle import PlanilhaControle
from src.servicos.processador import Processador
from src.utils.logger import configurar_logger, gravar_relatorio_csv


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
    p.add_argument("--linhas", type=_intervalo, help='intervalo de linhas da planilha, ex.: "2-50"')
    p.add_argument("--pedidos", nargs="+", help="processa só estes números de pedido")
    p.add_argument("--planilha", type=Path, help="caminho da planilha de controle")
    p.add_argument("--pasta-arquivos", type=Path, help="raiz das pastas dos processos")
    return p.parse_args()


def _sap_real(cfg, log):
    from src.sap.dialogo_arquivo import DialogoArquivo
    from src.sap.navegacao import SapNavigation
    from src.sap.pedidos import SapPedidos
    nav = SapNavigation()  # levanta SapNaoAbertoError / SapNaoLogadoError se for o caso
    return SapPedidos(nav, DialogoArquivo(cfg.timeout_dialogo_arquivo), cfg.transacao,
                      cfg.timeout_sap, cfg.coluna_titulo_anexos, log)


def _sap_simulado():
    """Cenários coerentes com a base fictícia (scripts/gerar_base_ficticia.py)."""
    from src.sap.simulado import SapSimulado
    return SapSimulado(
        inexistentes={"4500001006"},
        bloqueados={"4500001007"},
        anexos_iniciais={"4500001003": ["COA_PROC-2026-0003_lote1"]},
    )


def main() -> int:
    args = _args()
    cfg = cfg_mod.carregar()
    if args.planilha:
        cfg.planilha = args.planilha
    if args.pasta_arquivos:
        cfg.raiz_arquivos = args.pasta_arquivos

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
    log.info("Iniciando | planilha=%s (pedido=col %s, processo=col %s) | arquivos=%s | "
             "SharePoint (ref.)=%s", cfg.planilha, cfg.col_pedido, cfg.col_processo,
             cfg.raiz_arquivos, cfg.sharepoint_url)
    log.info("Andamento será gravado em: %s",
             f"coluna {cfg.col_status} da própria planilha" if cfg.gravar_status_na_planilha
             else cfg.arquivo_estado)

    try:
        sap = _sap_simulado() if args.simulado else _sap_real(cfg, log)
        planilha = PlanilhaControle(
            cfg.planilha, cfg.aba, log, col_pedido=cfg.col_pedido, col_processo=cfg.col_processo,
            col_status=cfg.col_status, col_obs=cfg.col_obs, col_data=cfg.col_data,
            linha_cabecalho=cfg.linha_cabecalho, gravar_na_planilha=cfg.gravar_status_na_planilha,
            arquivo_estado=cfg.arquivo_estado,
            pasta_backup=cfg.logs_dir / "backup_planilha" if cfg.backup_planilha else None)
        provedor = PastaSincronizada(cfg.raiz_arquivos, cfg.extensoes_permitidas, log=log,
                                     profundidade=cfg.profundidade_busca)
        proc = Processador(cfg, planilha, provedor, sap, log, dry_run=args.dry_run)
        resumo = proc.executar(limite=args.limite, reprocessar_erros=args.reprocessar_erros,
                               linhas=args.linhas, pedidos=set(args.pedidos or ()) or None)
    except ErroFatal as e:
        log.critical("Execução não pôde começar/continuar: %s", e)
        return 2

    relatorio = gravar_relatorio_csv(cfg.logs_dir, ts, resumo.resultados)
    log.info("Resumo: %s | relatório: %s", resumo.contagem(), relatorio)
    if resumo.abortado:
        log.critical("Execução ABORTADA: %s", resumo.motivo_aborto)
        return 2
    return 1 if resumo.contagem().get("ERRO") else 0


if __name__ == "__main__":
    sys.exit(main())
