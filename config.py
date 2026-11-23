"""Configuração central do robô. Tudo que muda de ambiente fica aqui.

Qualquer campo pode ser sobrescrito por variável de ambiente COA_<CAMPO>
(ex.: COA_RAIZ_ARQUIVOS=C:\\Users\\voce\\Empresa\\Comex - COA).
"""
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parent
# Dados FICTÍCIOS de demonstração: só são usados com `main.py --simulado`
PLANILHA_DEMO = RAIZ_PROJETO / "data" / "controle_coa.xlsx"
RAIZ_DEMO = RAIZ_PROJETO / "data" / "sharepoint_simulado"


@dataclass
class Config:
    # --- Base de controle (cópia da base do Power BI só com os processos que o robô deve ver) ---
    # O robô trabalha com a base REAL no SharePoint, lida pela pasta sincronizada do OneDrive.
    # url_base_controle: link do arquivo; dele sai a PASTA ('Controle robô COA'). Como o Power BI gera
    # um arquivo novo a cada exportação, vale o MAIS RECENTE da pasta que casa com padrao_base_controle.
    # (O link abaixo é o do arquivo, sem os parâmetros de compartilhamento '?d=...&csf=...'.)
    url_base_controle: str = (
        "https://iclgroup365.sharepoint.com/sites/ICLBRComexTeam/Shared%20Documents/IMPO-ADS/"
        "Controle%20rob%C3%B4%20COA/DATA%20BASE%20-%202026-11-11T152807.964.xlsx")
    padrao_base_controle: str = "DATA BASE*.xlsx"
    # Para escolher outro lugar: COA_PLANILHA=<arquivo .xlsx> ou <pasta> (usa a mais recente nela).
    planilha: Path | None = None
    aba: str | None = None          # None = primeira aba; COA_ABA="nome da aba" se houver várias
    # Colunas de ENTRADA: pelo NOME do cabeçalho (não depende da posição). Letra também vale (ex.: G).
    col_processo: str = "PROCESSO"  # '0226/25' na base = pasta '0226-25' (ou '0226_25') no SharePoint
    col_pedido: str = "PEDIDO SAP"  # número do pedido na ME22N
    linha_cabecalho: int = 1        # linha onde ficam os títulos das colunas
    # --- Quais linhas da base o robô deve tratar (critério vindo do sistema) ---
    # Se a base tiver uma coluna que diz se o processo precisa de COA (ex.: um status do sistema),
    # aponte-a em col_filtro e liste os valores:
    #   filtro_processar = só linhas com um destes valores  (ex.: "PENDENTE,SEM COA ANEXADO")
    #   filtro_ignorar   = todas, menos as com um destes valores
    # "<vazio>" representa célula em branco. Sem col_filtro, toda linha da base é considerada.
    col_filtro: str | None = None
    filtro_processar: tuple[str, ...] = ()
    filtro_ignorar: tuple[str, ...] = ()
    # Andamento do robô: o CSV (arquivo_estado) é a MEMÓRIA; as colunas abaixo, na cópia da base, são
    # o ESPELHO para a equipe ver. Se a cópia da base for substituída por dados novos (sem status),
    # o robô repõe o status do que já concluiu sem reabrir o SAP. Colunas indicadas por NOME são
    # criadas no fim da tabela se não existirem; por letra, precisam existir.
    #   em branco = o robô anexa | "JÁ ANEXADO" = concluído | "ERRO" = falhou | outro texto = pulada
    # gravar_status_na_planilha=False -> a base é só lida e o andamento fica só no CSV.
    gravar_status_na_planilha: bool = True
    col_status: str = "STATUS COA ROBÔ"
    col_obs: str | None = "OBS COA ROBÔ"    # motivo do ERRO / resumo do que foi anexado
    col_data: str | None = "DATA COA ROBÔ"  # data/hora do processamento
    trava_validade_horas: int = 3   # trava anti-execução-dupla: após isto é considerada abandonada
    salvar_a_cada: int = 5          # grava a planilha a cada N pedidos (e sempre ao terminar/abortar)
    backup_planilha: bool = True    # copia a planilha para logs/backup_planilha antes de gravar
    # Memória do robô (sempre usada), chave = pedido + processo:
    arquivo_estado: Path = RAIZ_PROJETO / "data" / "estado_processamento.csv"

    # --- Documentos dos processos no SharePoint ---
    # Pasta que CONTÉM as pastas de processo (0001-24, 0226-25...). Ordem de resolução:
    #   1) COA_RAIZ_ARQUIVOS (caminho local)   2) url_pasta_processos (link do SharePoint)
    #   3) pasta chamada nome_pasta_processos, procurada na mesma biblioteca da base de controle.
    # O robô NÃO baixa da internet: usa a pasta sincronizada pelo OneDrive.
    raiz_arquivos: Path | None = None
    # Link da pasta 'DOCS PROCESSOS IMPORTAÇÃO' (sem os parâmetros de rastreio do link copiado do navegador).
    url_pasta_processos: str | None = (
        "https://iclgroup365.sharepoint.com/sites/ICLBRComexTeam/Shared%20Documents/IMPO-ADS/"
        "DOCS%20PROCESSOS%20IMPORTA%C3%87%C3%83O")
    nome_pasta_processos: str = "DOCS PROCESSOS IMPORTAÇÃO"
    # () = anexa TUDO que estiver na pasta do processo (menos lixo: ~$*, Thumbs.db, .tmp...).
    # Para restringir: COA_EXTENSOES_PERMITIDAS=.pdf,.xlsx
    extensoes_permitidas: tuple[str, ...] = ()
    profundidade_busca: int = 1     # 2+ se as pastas de processo estiverem dentro de subpastas
    # True: se não houver pasta com o nome exato, tenta "começa com" (ex.: '0002-23 (ANTIGO ...)').
    # Isso lista a pasta raiz uma vez; False = só nome exato, nunca lista.
    buscar_pasta_por_prefixo: bool = True

    # --- SAP ---
    transacao: str = "ME22N"          # alteração de pedido: é nela que se anexa (a ME23N só exibe)
    timeout_sap: int = 30            # s esperando o SAP ficar livre
    timeout_dialogo_arquivo: int = 20  # s esperando a janela "Abrir" do Windows
    espera_janela_seguranca: float = 3.0  # s esperando o aviso "Segurança do SAP GUI" (Permitir) após escolher o arquivo
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
        if isinstance(atual, Path) or "Path" in str(f.type):
            # aceita %USERPROFILE% / $HOME e ~ (o mesmo .bat serve em qualquer PC/usuário)
            valor = Path(os.path.expandvars(os.path.expanduser(bruto)))
        elif isinstance(atual, bool):
            valor = bruto.lower() in ("1", "true", "sim")
        elif isinstance(atual, int):
            valor = int(bruto)
        elif isinstance(atual, float):
            valor = float(bruto.replace(",", "."))
        elif isinstance(atual, tuple):
            valor = tuple(x.strip().lower() for x in bruto.split(",") if x.strip())
        else:
            valor = bruto
        setattr(cfg, f.name, valor)
    return cfg
