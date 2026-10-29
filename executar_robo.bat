@echo off
chcp 65001 >nul
rem =====================================================================
rem  Executa o robo de anexo de COA. Use este arquivo no Agendador de Tarefas.
rem  Ajuste os caminhos abaixo UMA vez. Argumentos extras sao repassados ao robo,
rem  ex.:  executar_robo.bat --reprocessar-erros
rem =====================================================================

rem Planilha de controle (arquivo FECHADO no Excel durante a execucao)
set "COA_PLANILHA=C:\CAMINHO\DA\PLANILHA\DATA BASE.xlsx"
rem Pasta sincronizada do OneDrive que CONTEM as pastas dos processos (0001-24, 0001-25...)
set "COA_RAIZ_ARQUIVOS=C:\CAMINHO\DA\PASTA\SINCRONIZADA\DOCS PROCESSOS IMPORTACAO"
rem Letra da coluna de status que voce criou no fim da planilha
set "COA_COL_STATUS=T"
rem set "COA_ABA=nome da aba"

cd /d "%~dp0"
".venv\Scripts\python.exe" main.py %*
exit /b %ERRORLEVEL%
