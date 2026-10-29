"""IDs de elementos do SAP GUI usados pelo robô.

ATENÇÃO — VALIDAR NO SEU AMBIENTE. Estes IDs seguem o padrão que o gravador de scripts
do SAP costuma gerar para a ME23N / Serviços para objeto (GOS), mas variam com versão do
SAP GUI, tema e customizações. Para confirmar: no SAP, Alt+F12 > "Script Recording and
Playback", grave o passo manual e compare. Se algo diferir, ajuste SÓ este arquivo.
O script scripts/diagnostico_sap.py ajuda a conferir cada passo.
"""

# --- Seleção do pedido (ME23N) ---
BTN_OUTRO_PEDIDO = "wnd[0]/tbar[1]/btn[17]"                                   # "Outro pedido" (Shift+F5)
CAMPO_PEDIDO_DIALOGO = "wnd[1]/usr/subSUB0:SAPLMEGUI:0003/ctxtMEPO_SELECT-EBELN"

# --- Serviços para objeto (GOS) ---
GOS_BARRA = "wnd[0]/titl/shellcont/shell"
GOS_MENU = "%GOS_TOOLBOX"
GOS_CRIAR_ANEXO = "%GOS_PCATTA_CREATE"      # Criar > Criar anexo
GOS_LISTA_ANEXOS = "%GOS_VIEW_ATTA"         # Lista de anexos

# --- Lista de anexos (popup) --- PLACEHOLDER: confirmar com o gravador/diagnóstico
GRID_ANEXOS = "wnd[1]/usr/cntlCONTAINER_0100/shellcont/shell"
