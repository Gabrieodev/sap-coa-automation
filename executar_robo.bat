@echo off
chcp 65001 >nul
rem =====================================================================
rem  Executa o robo de anexo de COA. Use este arquivo no Agendador de Tarefas.
rem  Argumentos extras sao repassados ao robo,
rem  ex.:  executar_robo.bat --reprocessar-erros
rem =====================================================================

rem O robo usa a base de controle e os documentos REAIS, lidos das pastas SINCRONIZADAS do OneDrive
rem (caminhos abaixo). Para conferir o que o robo enxerga: scripts\localizar_pastas_sharepoint.py
rem O SAP GUI precisa estar ABERTO e LOGADO neste usuario (o robo nao faz login).

rem Base de controle REAL: copia da base do Power BI, na biblioteca sincronizada do SharePoint.
rem O nome do arquivo e fixo. %USERPROFILE% faz o mesmo .bat servir em qualquer usuario do PC.
set "COA_PLANILHA=%USERPROFILE%\ICL\ICL BR Comex Team - Documentos\IMPO-ADS\Controle robô COA\DATA BASE - 2026-11-11T152807.964.xlsx"
rem Pasta sincronizada com as pastas dos processos (0001-24, 0226-25...)
set "COA_RAIZ_ARQUIVOS=%USERPROFILE%\ICL\ICL BR Comex Team - Documentos\IMPO-ADS\DOCS PROCESSOS IMPORTAÇÃO"

rem Colunas de entrada, pelo NOME do cabecalho (padrao abaixo; letra tambem vale)
rem set "COA_COL_PROCESSO=PROCESSO"
rem set "COA_COL_PEDIDO=PEDIDO SAP"
rem Nomes das colunas do robo (criadas no fim da tabela se nao existirem):
rem set "COA_COL_STATUS=STATUS COA ROBÔ"
rem Criterio opcional: coluna da base que diz se o processo precisa de COA, e quais valores valem
rem set "COA_COL_FILTRO=I"
rem set "COA_FILTRO_PROCESSAR=PENDENTE"
rem Tipos de arquivo anexados (vazio = tudo que estiver na pasta do processo)
rem set "COA_EXTENSOES_PERMITIDAS=.pdf,.xlsx"
rem set "COA_ABA=nome da aba"

rem Confere antes de rodar: sem a base ou sem a pasta sincronizada, o Agendador mostra codigo 2.
if not exist "%COA_PLANILHA%" (
  echo [ERRO] Base de controle nao encontrada: %COA_PLANILHA%
  echo        O OneDrive esta sincronizando a biblioteca ICL BR Comex Team neste usuario?
  exit /b 2
)
if not exist "%COA_RAIZ_ARQUIVOS%\" (
  echo [ERRO] Pasta de documentos nao encontrada: %COA_RAIZ_ARQUIVOS%
  exit /b 2
)

cd /d "%~dp0"
".venv\Scripts\python.exe" main.py %*
exit /b %ERRORLEVEL%
