"""
Script de teste: cruzamento de vendas (LivePDV) com inadimplentes (Excel).

A logica:
  1. Le inadimplentes da planilha .xls(x) -> tem CNPJ + nome do titular
  2. Chama listar_fornecedores() do LivePDV -> tem CNPJ + nome fantasia da marca
  3. Mapa CNPJ -> nome fantasia
  4. Chama get_vendas_30d_por_nome() -> tem nome fantasia -> vendas
  5. Para cada inadimplente, busca nome fantasia pelo CNPJ, depois vendas pelo nome
"""

import os
import sys
import glob
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from livepdv_client import LivePDVClient, _norm_marca
from excel_inadimplentes import carregar_inadimplentes


def so_digitos(s):
    return re.sub(r"\D", "", str(s or ""))


def main():
    planilhas = sorted(glob.glob("*.xls*"))
    if not planilhas:
        print("ERRO: nenhuma planilha .xls*")
        sys.exit(1)
    planilha = planilhas[-1]
    print("planilha:", planilha)

    inad = carregar_inadimplentes(planilha)
    print("inadimplentes:", len(inad))

    cliente = LivePDVClient()
    cliente.login(os.environ["LIVEPDV_USERNAME"], os.environ["LIVEPDV_PASSWORD"])

    print("listando fornecedores...")
    fornecedores = cliente.listar_fornecedores(max_paginas=100)
    print("fornecedores:", len(fornecedores))

    cnpj_para_nome = {}
    for f in fornecedores:
        cnpj_norm = so_digitos(f.cnpj)
        if cnpj_norm:
            cnpj_para_nome[cnpj_norm] = f.nome
    print("CNPJs mapeados:", len(cnpj_para_nome))

    vendas = cliente.get_vendas_30d_por_nome(dias=30)
    print("nomes com venda 30d:", len(vendas))

    if vendas:
        print("amostras de vendas (top 5):")
        for nome, v in list(vendas.items())[:5]:
            print("  ", nome, "->", v)

    print("=== CRUZAMENTO ===")
    batidas = 0
    for i in inad:
        cnpj = so_digitos(i.get("cnpj"))
        nome_titular = i.get("nome", "")
        nome_fantasia = cnpj_para_nome.get(cnpj, "?")
        k = _norm_marca(nome_fantasia) if nome_fantasia != "?" else None
        v = vendas.get(k, 0.0) if k else None
        if v and v > 0:
            batidas += 1
        print(
            "  CNPJ", cnpj[:14].ljust(14),
            "| titular:", (nome_titular[:25] if nome_titular else "").ljust(25),
            "| marca:", (str(nome_fantasia)[:25] if nome_fantasia else "?").ljust(25),
            "| vendas:", v,
        )
    print("match:", batidas, "/", len(inad))


if __name__ == "__main__":
    main()
