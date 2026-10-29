"""Configuração central do robô. Tudo que muda de ambiente fica aqui.

Qualquer campo pode ser sobrescrito por variável de ambiente COA_<CAMPO>
(ex.: COA_RAIZ_ARQUIVOS=C:\\Users\\voce\\Empresa\\Comex - COA).
"""
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent


@dataclass
class Config:
    # --- Planilha de controle (pedido SAP <-> número do processo) ---
    # Em produção: COA_PLANILHA=<caminho da "Base de dados coa">
    planilha: Path = RAIZ_PROJETO / "data" / "controle_coa.xlsx"
    aba: str | None = None          # None = primeira aba; COA_ABA="nome da aba" se houver várias
    col_processo: str = "G"         # PROCESSO = nome da pasta no SharePoint (letra ou nome do cabeçalho)
    col_pedido: str = "H"           # PEDIDO SAP = número do pedido no SAP
    linha_cabecalho: int = 1        # linha onde ficam os títulos das colunas
    # Coluna de STATUS na própria planilha (você cria a coluna, com título, ao lado de PEDIDO SAP).
    # Em branco = o robô anexa; "JÁ ANEXADO" = concluído; "ERRO" = falhou; outro texto = pulada.
    gravar_status_na_planilha: bool = True
    col_status: str = "I"
    col_obs: str | None = None      # opcional: coluna onde o robô escreve o motivo do ERRO
    col_data: str | None = None     # opcional: coluna com data/hora do processamento
    salvar_a_cada: int = 5          # grava a planilha a cada N pedidos (e sempre ao terminar/abortar)
    backup_planilha: bool = True    # copia a planilha para logs/backup_planilha antes de gravar
    # Usado só se gravar_status_na_planilha=False (planilha apenas lida):
    arquivo_estado: Path = RAIZ_PROJETO / "data" / "estado_processamento.csv"

    # --- Arquivos do SharePoint ---
    # sharepoint_url é só referência para log (hoje, link provisório de desenvolvimento).
    # O robô NÃO acessa a URL: lê da pasta sincronizada pelo OneDrive. Em produção aponte
    # raiz_arquivos (COA_RAIZ_ARQUIVOS) para a pasta que CONTÉM as pastas de processo, ex.:
    # C:\Users\<voce>\ICL Group\<biblioteca> - Documents\<subpasta>
    sharepoint_url: str = ("https://iclgroup365.sharepoint.com/sites/ICLBRComexTeam/"
                           "Shared%20Documents/Forms/AllItems.aspx.linkoltrasecreto.com.br")
    raiz_arquivos: Path = RAIZ_PROJETO / "data" / "sharepoint_simulado"
    extensoes_permitidas: tuple[str, ...] = (".pdf",)
    profundidade_busca: int = 1     # 2+ se as pastas de processo estiverem dentro de subpastas

    # --- SAP ---
    transacao: str = "ME23N"
    timeout_sap: int = 30            # s esperando o SAP ficar livre
    timeout_dialogo_arquivo: int = 20  # s esperando a janela "Abrir" do Windows
    coluna_titulo_anexos: str = "BITM_DESCR"  # VALIDAR com scripts/diagnostico_sap.py

    # --- Resiliência ---
    tentativas_anexo: int = 2
    max_erros_inesperados_seguidos: int = 3

    # --- Saídas ---
    logs_dir: Path = RAIZ_PROJETO / "logs"


def carregar() -> Config:
    cfg = Config()
    for f in fields(cfg):
        bruto = os.environ.get(f"COA_{f.name.upper()}")
        if bruto is None:
            continue
        atual = getattr(cfg, f.name)
        if isinstance(atual, Path):
            valor = Path(bruto)
        elif isinstance(atual, bool):
            valor = bruto.lower() in ("1", "true", "sim")
        elif isinstance(atual, int):
            valor = int(bruto)
        elif isinstance(atual, tuple):
            valor = tuple(x.strip().lower() for x in bruto.split(","))
        else:
            valor = bruto
        setattr(cfg, f.name, valor)
    return cfg
