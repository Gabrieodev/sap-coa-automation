# sap-coa-automation

Robô que substitui o processo manual de **anexar o COA de comex no pedido de compra (SAP)**.

Para cada linha da **base** (`pedido_sap` ↔ `processo`), o robô vai direto à pasta daquele
processo no SharePoint (via pasta sincronizada do OneDrive), abre o pedido na ME22N e anexa **tudo
que está na pasta** e que ainda não está no pedido.

## Fluxo (resumo)

`python main.py` roda **de verdade**: SAP real, SharePoint real, base real e documentos reais.
(Dados fictícios só existem com `--simulado`.)

1. Acha a **base de controle** no SharePoint (`IMPO-ADS/Controle robô COA`): é a cópia da base do
   Power BI só com os processos que o robô deve enxergar. Se a pasta tiver várias exportações
   (`DATA BASE - 2026-11-11T152807.964.xlsx`…), usa a **mais recente**.
2. Lê só as linhas dessa base (colunas `PROCESSO` e `PEDIDO SAP`, achadas pelo **nome do cabeçalho**).
   Processo que não está na base é ignorado: a pasta dele no SharePoint nem é aberta.
3. Olha o **status** da linha (coluna `STATUS COA ROBÔ`, no fim da tabela; se a base vai até a CL, ela
   fica na CM e é **criada** se não existir). Em branco = tem que anexar; `JÁ ANEXADO`, `ERRO` ou outro
   texto = pula.
4. Para cada linha a anexar: vai à pasta do processo em `DOCS PROCESSOS IMPORTAÇÃO` (`0226/25` na base
   = pasta `0226-25` **ou** `0226_25`), abre o pedido na ME22N e anexa **tudo** que está na pasta.
5. Escreve o resultado (`JÁ ANEXADO`/`ERRO`, motivo, data) nas colunas do robô da mesma linha.

**`--simulado`** troca só o SAP por um de mentirinha. Sem `COA_PLANILHA`, usa também a base e os
documentos **fictícios** de `data\` (demonstração). Com a base real configurada, ele só roda com
`--dry-run` (nada é gravado): sem isso o robô gravaria `JÁ ANEXADO` falso na base real e no CSV, e
nunca mais anexaria esses pedidos. Por isso `--simulado` sem `--dry-run` com a base real é recusado.

Primeira vez no computador: `python scripts\localizar_pastas_sharepoint.py` mostra o que o OneDrive
sincroniza e o que o robô vai usar (a base e a pasta de documentos precisam estar **sincronizadas**
no OneDrive: no SharePoint, "Sincronizar" ou "Adicionar atalho ao OneDrive").

## Como o robô trabalha agora

1. **A base manda.** No SharePoint fica uma **cópia da base do Power BI** (colunas com os nomes de
   sempre; o robô acha `PROCESSO` e `PEDIDO SAP` pelo **nome**, não pela posição). O robô trata só os processos que estão nela; o resto
   do SharePoint é ignorado — nenhuma pasta fora da base é aberta nem listada. **Nunca mexe na base
   original do Power BI**: só na cópia.
2. **Nome do processo → nome da pasta.** Na base é `0226/25`; no SharePoint a `/` vira `-` (ou `_`),
   então a pasta é `0226-25` ou `0226_25` (se existirem as duas, é erro de ambiguidade). O robô monta esse nome e vai direto nela (sem varrer a biblioteca). Só se não
   houver pasta com o nome exato ele lista a raiz, **uma vez**, para achar pastas com sufixo
   (`0002-23 (ANTIGO 1-9145)`). Para proibir essa listagem: `COA_BUSCAR_PASTA_POR_PREFIXO=nao`.
3. **Anexa tudo da pasta**, não só o COA: PDF, Excel, Word, imagens, txt… Só ficam de fora lixo de
   sistema/Office (`~$*`, `Thumbs.db`, `desktop.ini`, `.tmp`…) e **subpastas** (o log avisa quando
   existem). Para restringir tipos: `COA_EXTENSOES_PERMITIDAS=.pdf,.xlsx`.
4. **Quais linhas da base valem** (opcional): se a base tiver uma coluna que diz se o processo
   precisa de COA, use `COA_COL_FILTRO` + `COA_FILTRO_PROCESSAR` (ou `COA_FILTRO_IGNORAR`).
   Linhas fora do critério não abrem pasta nem SAP. Sem `COA_COL_FILTRO`, toda linha da base vale.
5. **O robô preenche a cópia da base.** Cria no fim da tabela (se não existirem) as colunas
   `STATUS COA ROBÔ`, `OBS COA ROBÔ` e `DATA COA ROBÔ` e escreve só nelas (`JÁ ANEXADO` ou `ERRO`,
   motivo/resumo e data). Linhas repetidas do mesmo pedido (uma por material) recebem o mesmo status.
   Nenhuma outra célula é alterada.
6. **Cópia nova da base = rodar de novo.** Quando a cópia receber dados novos (mesmo sem as colunas
   do robô), o robô roda: o que já concluiu **volta a ser preenchido sem abrir o SAP**, e só o que
   é novo é anexado. Isso funciona porque a memória do robô é o CSV `data\estado_processamento.csv`
   (chave `pedido + processo`); a coluna na base é o espelho para a equipe. Apagar a linha do CSV
   (ou `--forcar --pedidos <n>`) refaz um pedido. Texto digitado à mão na coluna de status
   (ex.: `SEM COA`) é respeitado: a linha é pulada e o texto não é sobrescrito.

## Início rápido

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt

python -m pytest                      :: 211 testes, rodam sem SAP
python scripts\gerar_base_ficticia.py :: (re)cria base e pastas de demonstração
python main.py --simulado             :: roda tudo contra um SAP de mentirinha
python main.py --simulado --dry-run   :: idem, sem gravar nada (nem na base, nem no CSV)
python scripts\localizar_pastas_sharepoint.py :: mostra a base e os documentos REAIS que o robô usaria

:: demo com o critério da base ligado (coluna I = SITUAÇÃO COA; só "PENDENTE" vale):
set COA_COL_FILTRO=I
set COA_FILTRO_PROCESSAR=PENDENTE
python main.py --simulado --dry-run
```

## Rodando de verdade (SAP GUI aberto e logado)

1. `python main.py --teste-conexao` – abre a ME22N (equivale ao `main.py` original).
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
| `--forcar` | refaz mesmo o que consta como feito (exige `--pedidos` ou `--linhas`) |
| `--planilha`, `--pasta-arquivos` | sobrescrevem caminhos do `config.py` |

Saída: `0` tudo certo · `1` houve itens com erro · `2` execução abortada.

## Produção: o que configurar

Defina por variável de ambiente (ou edite `config.py`). No `cmd`: `set COA_PLANILHA=...`
(vale só para aquele terminal); para fixar, use "Variáveis de ambiente" do Windows.

| Variável | O que é | Padrão |
|---|---|---|
| `COA_PLANILHA` | (opcional) base de controle: arquivo `.xlsx` ou **pasta** (usa a mais recente). Sem isso, vem do link `url_base_controle` | pasta `IMPO-ADS/Controle robô COA` |
| `COA_PADRAO_BASE_CONTROLE` | nome dos arquivos de base quando `COA_PLANILHA` é pasta | `DATA BASE*.xlsx` |
| `COA_ABA` | nome da aba, se o arquivo tiver várias | primeira aba |
| `COA_COL_PROCESSO` | coluna do PROCESSO, no formato da base (`0226/25`): nome do cabeçalho (ou letra) | `PROCESSO` |
| `COA_COL_PEDIDO` | coluna do PEDIDO SAP: nome do cabeçalho (ou letra) | `PEDIDO SAP` |
| `COA_LINHA_CABECALHO` | linha dos títulos | `1` |
| `COA_RAIZ_ARQUIVOS` | (opcional) pasta **sincronizada do OneDrive** que contém as pastas de processo; sobrepõe o link | vem do link acima |
| `COA_URL_PASTA_PROCESSOS` | link da pasta de documentos no SharePoint (`IMPO-ADS/DOCS PROCESSOS IMPORTAÇÃO`); dele sai a pasta local | link em `config.py` |
| `COA_NOME_PASTA_PROCESSOS` | nome da pasta de documentos a procurar | `DOCS PROCESSOS IMPORTAÇÃO` |
| `COA_PROFUNDIDADE_BUSCA` | `2` se as pastas de processo estiverem dentro de subpastas (ex.: por ano) | `1` |
| `COA_COL_FILTRO` | (opcional) coluna da base que diz se o processo precisa de COA (letra ou cabeçalho) | — (toda linha vale) |
| `COA_FILTRO_PROCESSAR` | valores (separados por vírgula) que **devem** ser processados; `<vazio>` = célula em branco | — |
| `COA_FILTRO_IGNORAR` | valores que devem ser **ignorados** (todo o resto vale). Se os dois forem dados, vale `PROCESSAR` | — |
| `COA_BUSCAR_PASTA_POR_PREFIXO` | se não achar a pasta exata, tenta "começa com" (lista a raiz uma vez) | `sim` |
| `COA_COL_STATUS` | coluna de **STATUS** que o robô preenche. Por **nome** = criada no fim se não existir; por **letra** = precisa existir, com título. (Na base do BI a coluna I é `DATA CRIAÇÃO PEDIDO`: não use `I`) | `STATUS COA ROBÔ` |
| `COA_COL_OBS` | coluna do motivo do ERRO / resumo (vazio = não escreve) | `OBS COA ROBÔ` |
| `COA_COL_DATA` | coluna da data/hora do processamento (vazio = não escreve) | `DATA COA ROBÔ` |
| `COA_SALVAR_A_CADA` | grava a planilha a cada N pedidos (e sempre ao terminar/abortar/Ctrl+C) | `5` |
| `COA_BACKUP_PLANILHA` | copia a planilha p/ `logs\backup_planilha` antes da 1ª gravação | `sim` |
| `COA_GRAVAR_STATUS_NA_PLANILHA` | `sim` = preenche as colunas do robô na cópia da base; `nao` = base só lida, andamento só no CSV | `sim` |
| `COA_ARQUIVO_ESTADO` | CSV com a memória do robô (sempre gravado) | `data\estado_processamento.csv` |
| `COA_EXTENSOES_PERMITIDAS` | tipos anexados; vazio = **tudo** da pasta (menos lixo) | todos |

* **O robô não baixa nada pela internet.** Ele usa os **links** (`url_base_controle` em `config.py`,
  `COA_URL_PASTA_PROCESSOS`) só para descobrir qual é a pasta correspondente no disco, dentro do que
  o OneDrive sincroniza (`C:\Users\<voce>\<empresa>\<site> - Documents\...`). Se não achar, ele
  **para com uma mensagem** (nunca cai nos dados de demonstração). O link guardado é o do arquivo
  sem os parâmetros de compartilhamento (`?d=...&csf=...`), que não são necessários.
* **Coluna de status por letra (opcional).** Por padrão o robô cria as colunas pelo nome. Se preferir
  uma coluna sua, crie uma coluna ao lado de PEDIDO SAP (por padrão a **I**) com
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
0. Sincronize no OneDrive a pasta `Controle robô COA` e a `DOCS PROCESSOS IMPORTAÇÃO` e rode
   `python scripts\localizar_pastas_sharepoint.py`: ele deve mostrar a base mais recente e a pasta de
   documentos. Se a base já tiver pedidos com COA anexado à mão, marque `JÁ ANEXADO` na coluna
   `STATUS COA ROBÔ` antes (ou use o critério `COA_COL_FILTRO`).
1. (só se precisar fixar caminhos) `set COA_PLANILHA=...` e `set COA_RAIZ_ARQUIVOS=...` (e `COA_ABA`).
2. `python main.py --simulado --dry-run --limite 5`: com a base e os documentos reais resolvidos
   (o `--simulado` só troca o SAP por um de mentirinha), valida leitura e localização das pastas
   **sem tocar no SAP e sem gravar na base**.
3. `python scripts\diagnostico_sap.py <pedido real>` (valida os seletores).
4. `python main.py --dry-run --linhas 2-6` (SAP real, sem anexar).
5. `python main.py --linhas 2-6` e confira os anexos no SAP.
6. Só então ampliar.

> **Cuidado com linhas antigas.** Se a base tem pedidos cujo COA já foi anexado manualmente, o robô
> não sabe disso: ele compara o **nome** dos arquivos da pasta com os anexos do pedido e, se o nome
> for diferente, anexa de novo. Use o critério da base (`COA_COL_FILTRO`) para deixar de fora o que
> já foi feito, ou comece por um trecho recente (`--linhas`) e confira.
>
> **Pasta que ganha arquivos depois.** Processo concluído (`CONCLUIDO` no CSV) não é revisitado. Se
> chegarem arquivos novos na pasta depois, apague a linha dele de `estado_processamento.csv` (ou
> use `--reprocessar-erros` só para os que deram erro) para o robô conferir de novo; ele só anexa o
> que falta.

## Planilha de controle

Lê só as colunas configuradas (`PROCESSO`, `PEDIDO SAP` e, se ligado, a do critério) e escreve só nas
colunas do robô (`STATUS COA ROBÔ`, `OBS COA ROBÔ`, `DATA COA ROBÔ`), criadas depois da última coluna
com título (CL → CM, CN, CO). Cabeçalho repetido (duas colunas `PEDIDO SAP`) é recusado em vez de
adivinhado. Linhas inválidas (pedido vazio/não numérico, processo vazio, mesmo pedido com processos
diferentes) viram `ERRO` sem tocar no SAP; duplicatas exatas viram `IGNORADO`.

**Dica para a base antiga:** se há pedidos cujo COA já foi anexado manualmente, preencha a coluna
de status com `JÁ ANEXADO` nessas linhas **antes** da primeira execução (arrastar para baixo
resolve). O robô só processa o que estiver em branco.

## Fluxo de uma execução (passo a passo)

**Início**
1. Lê `config.py` + variáveis `COA_*` e abre `logs\execucao_<data>.log`.
2. Conecta ao SAP GUI já aberto e logado (se não estiver: encerra com código 2).
3. Abre a base (lê uma cópia local), localiza as colunas (o log mostra letra e cabeçalho de cada uma), lê as linhas e
   valida (pedido vazio/não numérico, processo vazio, conflitos, duplicatas).
4. Monta a fila: descarta linhas fora do critério da base (se configurado); das restantes, as sem
   andamento no CSV (+ `ERRO` se `--reprocessar-erros`), aplicando `--linhas`, `--pedidos` e `--limite`.

**Para cada linha da fila**
1. Vai direto à pasta do processo (`0226/25` na base = pasta `0226-25` no SharePoint) e lista os
   arquivos da pasta (menos lixo). Sem pasta / ambígua / vazia → `ERRO`, **sem abrir o SAP**.
2. Abre o pedido na ME22N. Pedido inexistente, bloqueado ou sem autorização → `ERRO`.
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
`0x1` = houve linhas com `ERRO`, `0x2` = abortou, `0x3` = já havia outra execução) e os arquivos em `logs\`.

**Duas execuções ao mesmo tempo.** O Agendador já evita duas instâncias da *tarefa*, mas não impede você
de rodar o robô à mão enquanto a tarefa roda. Por isso o robô cria `data\robo.lock` ao começar e o apaga
ao terminar; havendo outra execução, ele sai com código `3` sem tocar em nada. Se uma execução morreu
sem apagar a trava (queda de energia, tarefa interrompida), ela expira sozinha em 3 h
(`COA_TRAVA_VALIDADE_HORAS`) ou você apaga o arquivo.

**A base tem nome fixo e é sobrescrita pelo Power BI.** Tudo bem: quando a cópia chegar com dados novos
(sem as colunas do robô), a próxima execução repõe o status do que já foi feito a partir do CSV e só
anexa o que é novo. Evite rodar o robô no minuto em que a base está sendo substituída; marque o horário
da tarefa depois da atualização.

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
3. **Janelas do Windows no anexo** (`src/sap/dialogo_arquivo.py`) — usa `pywinauto` e trata duas
   janelas: **"Abrir"** (escolher o arquivo) e **"Segurança do SAP GUI"** (botão **Permitir**), em
   qualquer ordem; se a segunda não aparecer (alguém marcou "lembrar minha decisão"), segue. Os
   títulos mudam com o idioma (ajuste `TITULO_RE`, `TITULO_SEGURANCA_RE`, `BOTAO_PERMITIR_RE`).
   Para ver os títulos e botões EXATOS da sua máquina: `python scripts\listar_janelas.py` e faça um
   anexo à mão. Roda em thread porque a chamada do SAP bloqueia enquanto a janela estiver aberta.
4. **Pedido aberto por outro usuário na ME22N.** A ME22N bloqueia o pedido para edição. O robô
   classifica o bloqueio como `ERRO` ("bloqueado") se o SAP responder com mensagem de erro na barra
   de status; se o SAP mostrar um popup perguntando se abre em modo de exibição, o comportamento
   precisa ser validado com um pedido realmente bloqueado.
5. Como o SAP exibe o título do anexo (com/sem extensão) — afeta a conferência de duplicidade.
   Agora que a pasta vai inteira, isto importa mais: dois arquivos com o mesmo nome-base
   (`COA.pdf` e `COA.xlsx`) só se distinguem se o SAP mostrar a extensão. Se mostrar só o nome-base
   e o pedido tiver apenas um deles, o robô **não adivinha**: marca `ERRO` pedindo conferência manual
   em vez de duplicar ou deixar de anexar.

## Anexo na ME22N (fluxo)

Com o pedido aberto na **ME22N**: *Serviços para objeto* → *Criar* → *Criar anexo* → janela **Abrir**
(o robô cola o caminho do arquivo) → aviso **Segurança do SAP GUI** → **Permitir**. Repete para cada
arquivo da pasta. A ME22N **bloqueia** o pedido aberto para os demais usuários; por isso o robô, ao
trocar de pedido, solta o anterior e, ao terminar (inclusive com erro ou Ctrl+C), **sai da transação**
(volta à tela inicial do SAP) para não deixar o último pedido preso.

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
src/arquivos/sharepoint_local.py  link do SharePoint → pasta sincronizada; base mais recente
src/ambiente.py            resolve base e documentos reais (ou para com mensagem clara)
src/utils/nomes.py         processo→pasta ('/'→'-'), conferência de anexos, normalização do critério
tests/                     211 testes (base, arquivos, processador, SapPedidos c/ sessão falsa, main ponta a ponta)
```

## Próximos passos possíveis

* Trocar `PastaSincronizada` por leitura via Microsoft Graph (implementar `ProvedorArquivos`).
* Agendar a execução (Agendador de Tarefas) — exige sessão SAP logada.
