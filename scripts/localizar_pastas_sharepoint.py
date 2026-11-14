"""Mostra, neste computador, onde o robô vai ler a base de controle e as pastas de documentos.

Uso:  python scripts\\localizar_pastas_sharepoint.py
Não altera nada: só lista o que o OneDrive sincroniza e o que o robô escolheria.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfg_mod  # noqa: E402
from src.ambiente import resolver_planilha, resolver_raiz_arquivos  # noqa: E402
from src.arquivos import sharepoint_local as sp  # noqa: E402
from src.erros import ErroFatal  # noqa: E402


def main() -> int:
    cfg = cfg_mod.carregar()
    site = sp.interpretar_link(cfg.url_base_controle).site
    print(f"Site do SharePoint: {site}")
    raizes = sp.raizes_onedrive()
    print("\nRaízes do OneDrive encontradas:")
    print("\n".join(f"  {r}" for r in raizes) or "  (nenhuma) -> o OneDrive está instalado e logado?")
    print("\nBibliotecas sincronizadas deste site:")
    print("\n".join(f"  {b}" for b in sp.bibliotecas_locais(site, raizes)) or "  (nenhuma)")

    codigo = 0
    print("\n--- Base de controle ---")
    try:
        base = resolver_planilha(cfg)
        print(f"O robô usaria: {base}")
        outras = sorted(f.name for f in base.parent.glob("*.xlsx") if not f.name.startswith("~$"))
        if len(outras) > 1:
            print(f"(a pasta tem {len(outras)} arquivos .xlsx; vale o mais recente que casa com "
                  f"'{cfg.padrao_base_controle}')")
    except ErroFatal as e:
        codigo = 1
        print(f"NÃO RESOLVIDA: {e}")

    print("\n--- Documentos dos processos ---")
    try:
        raiz = resolver_raiz_arquivos(cfg)
        n = sum(1 for p in raiz.iterdir() if p.is_dir())
        print(f"O robô usaria: {raiz}  ({n} pastas)")
        print("Para fixar, no executar_robo.bat:")
        print(f'  set "COA_RAIZ_ARQUIVOS={raiz}"')
    except (ErroFatal, OSError) as e:
        codigo = 1
        print(f"NÃO RESOLVIDA: {e}")
        print("Informe o link da pasta (COA_URL_PASTA_PROCESSOS) ou o caminho (COA_RAIZ_ARQUIVOS).")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
