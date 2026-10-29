# sap-coa-automation

Robô que substitui o processo manual de **anexar o COA de comex no pedido de compra (SAP)**.

Para cada linha da planilha de controle (`pedido_sap` ↔ `processo`), o robô localiza a pasta do
processo no SharePoint (via pasta sincronizada do OneDrive), abre o pedido na ME23N e anexa os
PDFs que ainda não estão lá.

## Início rápido

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt

python -m pytest                      :: 122 testes, rodam sem SAP
python scripts\gerar_base_ficticia.py :: (re)cria planilha e pastas de demonstração
python main.py --simulado             :: roda tudo contra um SAP de mentirinha
python main.py --simulado --dry-run   :: idem, sem alterar a planilha
```

## Rodando de verdade (SAP GUI aberto e logado)

1. `python main.py --teste-conexao` – abre a ME23N (equivale ao `main.py` original).
2. `python scripts\diagnostico_sap.py <pedido real>` – confere os seletores (ver abaixo).
3. `python main.py --dry-run --limite 3` – SAP real, mas **não anexa** e não altera a planilha.
4. `python main.py --limite 3` – 3 pedidos de verdade; confira no SAP.
5. `python main.py` – execução completa.

| Opção | O que faz |
|---|---|
| `--simulado` | SAP de mentirinha (não precisa de SAP GUI nem Windows) |
| `--dry-run` | abre pedidos e lista anexos, mas não anexa e não escreve na planilha |
| `--limite N` | processa no máximo N pedidos |
| `--linhas 2-50` | só as linhas 2 a 50 da planilha (`100-` = da 100 em diante) |
| `--pedidos 4500… 4500…` | só estes números de pedido |
| `--reprocessar-erros` | tenta de novo as linhas com `ERRO` |
| `--planilha`, `--pasta-arquivos` | sobrescrevem caminhos do `config.py` |

Saída: `0` tudo certo · `1` houve itens com erro · `2` execução abortada.

## Produção: o que configurar

Defina por variável de ambiente (ou edite `config.py`). No `cmd`: `set COA_PLANILHA=...`
(vale só para aquele terminal); para fixar, use "Variáveis de ambiente" do Windows.

| Variável | O que é | Padrão |
|---|---|---|
| `COA_PLANILHA` | caminho da "Base de dados coa" (.xlsx) | `data\controle_coa.xlsx` (demo) |
| `COA_ABA` | nome da aba, se o arquivo tiver várias | primeira aba |
| `COA_COL_PROCESSO` | coluna do PROCESSO (letra ou nome do cabeçalho) | `G` |
| `COA_COL_PEDIDO` | coluna do PEDIDO SAP | `H` |
| `COA_LINHA_CABECALHO` | linha dos títulos | `1` |
| `COA_RAIZ_ARQUIVOS` | pasta **sincronizada do OneDrive** que contém as pastas de processo | `data\sharepoint_simulado` (demo) |
| `COA_PROFUNDIDADE_BUSCA` | `2` se as pastas de processo estiverem dentro de subpastas (ex.: por ano) | `1` |
| `COA_COL_STATUS` | coluna de **STATUS** onde o robô escreve (você cria a coluna, com título) | `I` |
| `COA_COL_OBS` | (opcional) coluna para o motivo do ERRO | — |
| `COA_COL_DATA` | (opcional) coluna para data/hora do processamento | — |
| `COA_SALVAR_A_CADA` | grava a planilha a cada N pedidos (e sempre ao terminar/abortar/Ctrl+C) | `5` |
| `COA_BACKUP_PLANILHA` | copia a planilha p/ `logs\backup_planilha` antes da 1ª gravação | `sim` |
| `COA_GRAVAR_STATUS_NA_PLANILHA` | `nao` = planilha só lida; andamento vai para `COA_ARQUIVO_ESTADO` (CSV) | `sim` |
| `COA_EXTENSOES_PERMITIDAS` | tipos anexados | `.pdf` |

* **O robô não acessa a URL do SharePoint.** `sharepoint_url` serve só de referência no log.
  Ele lê os arquivos da pasta que o OneDrive sincroniza no seu PC (no Explorer, clique em
  "Sincronizar" na biblioteca do SharePoint e use o caminho que aparecer).
* **Coluna de status na planilha.** Crie uma coluna ao lado de PEDIDO SAP (por padrão a **I**) com
  um título (ex.: `STATUS`) — o robô não cria nem adivinha a coluna, e recusa rodar se ela não
  tiver título. Regras:

  | Conteúdo da célula | O que o robô faz |
  |---|---|
  | em branco (ou `PENDENTE`) | **processa** |
  | `JÁ ANEXADO` (ou `CONCLUIDO`) | pula |
  | `ERRO` | pula (use `--reprocessar-erros` para tentar de novo) |
  | qualquer outro texto (`SEM COA`, `AGUARDANDO FORNECEDOR`…) | **pula e nunca sobrescreve**; aparece um aviso no log |

  Ao terminar cada pedido ele escreve `JÁ ANEXADO` ou `ERRO` (motivo em `COA_COL_OBS`, se definida)
  **só na coluna de status**; nenhuma outra célula é alterada.
* **Proteções porque a base é compartilhada**: (1) na hora de gravar, o arquivo é relido do disco e
  o status só entra se aquela linha ainda tiver o mesmo pedido/processo lidos no início — se alguém
  inseriu/apagou linhas durante a execução, o status **não é gravado** e o log/relatório avisam;
  (2) se alguém digitou um status manual no meio-tempo, ele não é sobrescrito; (3) gravação
  atômica (arquivo temporário + troca): queda no meio não corrompe a base; (4) backup da planilha
  em `logs\backup_planilha` antes da 1ª gravação; (5) se a planilha estiver aberta no Excel, o robô
  tenta de novo e, se não der, segue e guarda tudo no relatório CSV.
* **Feche a planilha no Excel antes de rodar** e evite editá-la durante a execução.
* **Escolha uma coluna livre.** Se `COA_COL_STATUS` apontar para uma coluna que já tem outro conteúdo
  (ex.: `DATA CRIAÇÃO PEDIDO`), o robô recusa rodar e avisa. Crie uma coluna nova (de preferência no
  fim da tabela, para não deslocar as demais) com título próprio, ex.: `STATUS COA ROBÔ`.
* **Se a base for regenerada** (exportação que substitui o arquivo, nome com data/hora), a coluna de
  status se perderia a cada nova versão: nesse caso use `COA_GRAVAR_STATUS_NA_PLANILHA=nao`
  (planilha só lida; andamento em `data\estado_processamento.csv`).
* Ao iniciar, o log mostra `Coluna processo lida de G (cabeçalho: 'PROCESSO')` — **confira essas
  duas linhas** antes de qualquer execução: se o cabeçalho impresso não for o esperado, a coluna
  está errada.

## Checklist antes da primeira execução real

0. **Rode `python scripts\verificar_planilha.py "<caminho da base>"` numa cópia da planilha real.**
   O robô grava com openpyxl, que reescreve o arquivo inteiro e descarta o que não conhece
   (conexões de dados/Power Query, segmentações, comentários encadeados, formas...). O script mostra
   o que seria perdido (código de saída 1 = perderia algo importante; nesse caso use
   `COA_GRAVAR_STATUS_NA_PLANILHA=nao`). Ele nunca altera o arquivo original.
0. Na planilha, crie a coluna de **STATUS** ao lado de PEDIDO SAP (título preenchido) e, na base
   antiga, marque `JÁ ANEXADO` onde o COA já foi anexado.
1. `set COA_PLANILHA=...` e `set COA_RAIZ_ARQUIVOS=...` (e `COA_ABA`/`COA_COL_STATUS` se necessário).
2. `python main.py --simulado --dry-run --limite 5` apontando para a base real: valida leitura da
   planilha e localização das pastas **sem tocar no SAP e sem gravar na planilha**.
3. `python scripts\diagnostico_sap.py <pedido real>` (valida os seletores).
4. `python main.py --dry-run --linhas 2-6` (SAP real, sem anexar).
5. `python main.py --linhas 2-6` e confira os anexos no SAP.
6. Só então ampliar.

> **Cuidado com linhas antigas.** Se a base tem pedidos cujo COA já foi anexado manualmente, o robô
> não sabe disso: ele compara o **nome** dos arquivos da pasta com os anexos do pedido e, se o nome
> for diferente, anexa de novo. Comece por um trecho recente (`--linhas`) e confira.

## Planilha de controle

Lê só as colunas configuradas (G = PROCESSO, H = PEDIDO SAP) e escreve só na de status (I).
Linhas inválidas (pedido vazio/não numérico, processo vazio, mesmo pedido com processos
diferentes) viram `ERRO` sem tocar no SAP; duplicatas exatas viram `IGNORADO`.

**Dica para a base antiga:** se há pedidos cujo COA já foi anexado manualmente, preencha a coluna
de status com `JÁ ANEXADO` nessas linhas **antes** da primeira execução (arrastar para baixo
resolve). O robô só processa o que estiver em branco.

## Fluxo de uma execução (passo a passo)

**Início**
1. Lê `config.py` + variáveis `COA_*` e abre `logs\execucao_<data>.log`.
2. Conecta ao SAP GUI já aberto e logado (se não estiver: encerra com código 2).
3. Abre a planilha, localiza as colunas (o log mostra letra e cabeçalho de cada uma), lê as linhas e
   valida (pedido vazio/não numérico, processo vazio, conflitos, duplicatas).
4. Monta a fila: linhas com status em branco (+ `ERRO` se `--reprocessar-erros`), aplicando
   `--linhas`, `--pedidos` e `--limite`.

**Para cada linha da fila**
1. Procura a pasta do processo (`0226/25` na planilha = pasta `0226-25` no SharePoint) e lista os
   arquivos elegíveis. Sem pasta / ambígua / sem PDF → `ERRO`, **sem abrir o SAP**.
2. Abre o pedido na ME23N. Pedido inexistente, bloqueado ou sem autorização → `ERRO`.
3. Lista os anexos que o pedido já tem e separa o que falta.
4. Anexa cada arquivo que falta (Serviços para objeto → Criar anexo → janela "Abrir" do Windows).
5. Lista de novo e confere que cada arquivo apareceu. Se não apareceu → `ERRO`.
6. Marca a linha (`JÁ ANEXADO` / `ERRO`). A gravação na planilha acontece a cada N pedidos.

**Encerramento**
* Grava o que faltar na planilha (sempre, mesmo se abortar ou der Ctrl+C), gera
  `logs\relatorio_<data>.csv` e imprime o resumo (`{'CONCLUIDO': n, 'ERRO': n, ...}`).
* Código de saída: `0` tudo certo · `1` houve linhas com `ERRO` · `2` execução abortada (SAP
  caiu/deslogou, 3 falhas técnicas seguidas, planilha inválida, Ctrl+C).
* Linhas não alcançadas por causa de um aborto continuam em branco e entram na próxima execução.

## Execução diária (Agendador de Tarefas)

O robô foi feito para rodar todo dia sem desperdiçar tempo:
* Linhas `JÁ ANEXADO` (e `IGNORADO`, `ERRO`, ou texto manual) **não abrem pasta nem pedido**; só as
  linhas em branco são processadas.
* **Sem nada pendente, o robô nem conecta ao SAP** e termina com código `0` em segundos. O SAP só é
  acionado quando o primeiro pedido realmente precisar dele.
* Pedidos novos na planilha são pegos automaticamente no dia seguinte.

**Configuração no Agendador** (Win+R → `taskschd.msc` → Criar Tarefa):

| Aba | Ajuste |
|---|---|
| Geral | **"Executar somente quando o usuário estiver conectado"** — o SAP GUI e a janela "Abrir" exigem a sessão do Windows aberta (não use "executar estando o usuário conectado ou não") |
| Disparadores | diário, num horário em que o SAP esteja **aberto e logado** nesse usuário |
| Ações | Programa: `executar_robo.bat` (caminho completo) · Argumentos (opcional): `--reprocessar-erros` · Iniciar em: a pasta do projeto |
| Condições | desmarque "Iniciar somente com energia CA" se for notebook |
| Configurações | "Interromper se executar por mais de" ex. 2 horas · "Se já estiver em execução, **não** iniciar nova instância" |

Edite os caminhos no início de `executar_robo.bat` (uma vez).

**`--reprocessar-erros` no agendamento?** Sem ele, uma linha que deu `ERRO` fica parada até alguém
limpar o status. Com ele, o robô tenta de novo todo dia: útil quando o erro foi "pasta ainda não
existe no SharePoint" (falha antes de abrir o SAP, custo zero). O custo são erros definitivos do
SAP (pedido inexistente/bloqueado), que reabrem o pedido todo dia — para pará-los, escreva um texto
manual na célula de status (ex.: `SEM COA`).

**Como saber se deu certo:** `Último Resultado da Execução` no Agendador (`0x0` = tudo certo,
`0x1` = houve linhas com `ERRO`, `0x2` = abortou) e os arquivos em `logs\`.

**Atenção:** a tarefa não funciona com o SAP deslogado (por inatividade, por exemplo) nem com a
planilha aberta no Excel. Teste antes com a tela bloqueada se pretende depender disso. Cada execução
que grava na planilha gera um backup em `logs\backup_planilha`; apague os antigos de vez em quando.

## Como o robô lida com erros

| Situação | Comportamento |
|---|---|
| Pasta ausente / ambígua / sem PDF / arquivo vazio | `ERRO` no item, segue (SAP nem é aberto) |
| Pedido inexistente, bloqueado, sem autorização | `ERRO` no item, fecha popups, segue |
| Falha ao anexar | repete (`tentativas_anexo`); se persistir, `ERRO` informando o que já entrou |
| Anexo enviado mas ausente da lista | `ERRO` (não declara sucesso sem conferir) |
| SAP fechado/deslogado/sessão perdida | **aborta**; o que faltou continua pendente |
| N falhas técnicas seguidas (padrão 3) | **aborta** (disjuntor: provável seletor/ambiente) |
| Planilha aberta no Excel / sem permissão | tenta de novo; se não der, segue e mantém pendente (o relatório CSV garante o registro) |
| Linha da planilha mudou durante a execução | **não grava** o status daquela linha e avisa (nunca marca a linha errada) |

**Idempotência:** antes de anexar, lista os anexos do pedido e envia só o que falta (comparando o
nome-base, sem extensão/caixa). Rodar duas vezes não duplica.

Cada execução gera `logs/execucao_<data>.log` e `logs/relatorio_<data>.csv` (abre no Excel).

## ⚠️ Pontos a validar no SAP real

Eu não tinha acesso a um SAP, então estes itens foram escritos pelo padrão usual e **precisam ser
conferidos** (o `diagnostico_sap.py` ajuda):

1. **`src/sap/seletores.py`** — todos os IDs de tela ficam aí. Confirme com o gravador
   (Alt+F12 → *Script Recording and Playback*). O ID do grid da lista de anexos (`GRID_ANEXOS`) é
   o menos certo.
2. **`coluna_titulo_anexos`** (`config.py`) — nome técnico da coluna de título no grid.
3. **Janela "Abrir" do Windows** (`src/sap/dialogo_arquivo.py`) — usa `pywinauto`; o título muda
   com o idioma (ajuste `TITULO_RE`). Roda em thread porque a chamada do SAP bloqueia enquanto a
   janela estiver aberta.
4. Se o seu perfil permite **anexar com o pedido em modo de exibição** (ME23N).
5. Como o SAP exibe o título do anexo (com/sem extensão) — afeta a conferência de duplicidade.

## Estrutura

```
main.py                    ponto de entrada (argumentos, logs, relatório)
config.py                  caminhos, timeouts, tentativas
models/item.py             ItemControle, Resultado, status
src/erros.py               ErroDeItem (segue) x ErroFatal (aborta)
src/planilha/controle.py   lê G/H, grava o STATUS (conferindo a linha, atômico, com backup)
src/planilha/estado.py     modo alternativo: andamento em CSV, planilha só lida
src/arquivos/provedor.py   ProvedorArquivos + PastaSincronizada (OneDrive/SharePoint)
src/servicos/processador.py loop principal + política de erros + idempotência
src/sap/conexao|sessao|navegacao.py   (seu código original, ampliado)
src/sap/seletores.py       IDs de tela do SAP
src/sap/pedidos.py         abrir pedido, listar anexos, anexar (única classe que conhece telas)
src/sap/dialogo_arquivo.py janela "Abrir" do Windows (pywinauto, em thread)
src/sap/simulado.py        SAP de mentirinha p/ testes e --simulado
scripts/gerar_base_ficticia.py · scripts/diagnostico_sap.py · scripts/verificar_planilha.py
tests/                     122 testes (planilha e status, arquivos, processador, SapPedidos c/ sessão falsa, main ponta a ponta)
```

## Próximos passos possíveis

* Trocar `PastaSincronizada` por leitura via Microsoft Graph (implementar `ProvedorArquivos`).
* Agendar a execução (Agendador de Tarefas) — exige sessão SAP logada.
