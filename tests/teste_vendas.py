"""
Script de teste: cruzamento de vendas (LivePDV) com inadimplentes (Excel).

Uso (no Colab):
    !python tests/teste_vendas.py
"""

import os
import sys
import glob

# Garante que conseguimos importar os modulos do projeto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from livepdv_client import LivePDVClient, _norm_marca
from excel_inadimplentes import carregar_inadimplentes


def main():
    planilhas = sorted(glob.glob("*.xls*"))
    if not planilhas:
        print("ERRO: nenhuma planilha .xls* encontrada no diretorio atual")
        sys.exit(1)
    planilha = planilhas[-1]
    print("planilha:", planilha)

    inad = carregar_inadimplentes(planilha)
    print("inadimplentes:", len(inad))

    cliente = LivePDVClient()
    cliente.login(
        os.environ["LIVEPDV_USERNAME"],
        os.environ["LIVEPDV_PASSWORD"],
    )

    vendas = cliente.get_vendas_30d_por_nome(dias=30)
    print("expositores com venda 30d:", len(vendas))

    if vendas:
        print("amostras de vendas:")
        for nome, v in list(vendas.items())[:5]:
            print("  ", nome, "->", v)

    batidas = 0
    for i in inad:
        nome = i["nome"]
        k = _norm_marca(nome)
        v = vendas.get(k, 0.0)
        if v > 0:
            batidas += 1
        print(
            "  ",
            (nome[:30] if nome else "").ljust(30),
            "-> norm=",
            (k[:30] if k else "").ljust(30),
            "-> vendas=",
            v,
        )
    print("match:", batidas, "/", len(inad))


if __name__ == "__main__":
    main()
