"""Erros de domínio do robô (não ligados ao SAP).

Regra de ouro do loop principal:
- ErroDeItem  -> problema só naquele pedido: registra, marca ERRO e segue para o próximo.
- ErroFatal   -> o robô não consegue continuar (SAP caiu, planilha sumiu): aborta a execução.
"""


class ErroDeItem(Exception):
    """Erro recuperável: afeta apenas o item (pedido/processo) em andamento.

    `tecnico=True` marca falhas que, se se repetirem em sequência, indicam problema do
    robô/ambiente (seletor errado, diálogo travado) e não dos dados — o disjuntor do
    loop principal conta apenas essas.
    """
    tecnico = False


class ErroFatal(Exception):
    """Erro que impede a continuação da execução inteira."""


class DadosInvalidosError(ErroDeItem):
    """Linha da planilha com pedido/processo vazio, malformado ou conflitante."""


class PastaProcessoNaoEncontradaError(ErroDeItem):
    """Não existe pasta para o número do processo."""


class PastaProcessoAmbiguaError(ErroDeItem):
    """Mais de uma pasta casa com o número do processo."""


class SemArquivosError(ErroDeItem):
    """A pasta do processo existe, mas não tem nenhum arquivo elegível."""


class ArquivoIndisponivelError(ErroDeItem):
    """Arquivo ainda só na nuvem (OneDrive) ou ilegível."""


class AnexoFalhouError(ErroDeItem):
    """O SAP/diálogo de arquivo não concluiu o anexo."""
    tecnico = True


class AnexoNaoConfirmadoError(ErroDeItem):
    """O anexo foi enviado, mas não aparece na lista de anexos do pedido."""
    tecnico = True


class PlanilhaError(ErroFatal):
    """Planilha de controle ausente, ilegível ou sem as colunas obrigatórias."""
