"""
relatorio_inadimplentes.py
==========================

Une LivePDV (lista de marcas/expositores) + Efí (cobranças vencidas)
para gerar um relatório consolidado de marcas inadimplentes.

Uso:
    python relatorio_inadimplentes.py --mock                   # exemplo rápido
    python relatorio_inadimplentes.py --real                   # produção
    python relatorio_inadimplentes.py --real --csv             # exporta CSV
    python relatorio_inadimplentes.py --real --cnpj 00000      # uma marca só
    python relatorio_inadimplentes.py --real --dias 7          # só >= 7 dias atraso

Saída: tabela ASCII no terminal + opcional CSV em ./relatorios/.

Este script é SEGURO de rodar em modo --mock sem nenhuma credencial.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional


# ============================================================================
# Tabela: usa 'tabulate' se disponível, senão fallback puro
# ============================================================================
try:
    from tabulate import tabulate  # type: ignore

    _HAS_TABULATE = True
except ImportError:
    _HAS_TABULATE = False


def _formatar_tabela(headers: list[str], linhas: list[list]) -> str:
    if _HAS_TABULATE:
        return tabulate(linhas, headers=headers, tablefmt="rounded_outline")
    # Fallback simples
    larguras = [
        max(len(str(h)), max((len(str(r[i])) for r in linhas), default=0))
        for i, h in enumerate(headers)
    ]
    sep = "+-" + "-+-".join("-" * w for w in larguras) + "-+"
    out = [sep]
    out.append("| " + " | ".join(str(h).ljust(w) for h, w in zip(headers, larguras)) + " |")
    out.append(sep)
    for r in linhas:
        out.append("| " + " | ".join(str(c).ljust(w) for c, w in zip(r, larguras)) + " |")
    out.append(sep)
    return "\n".join(out)


# ============================================================================
# Modelo de uma linha do relatório
# ============================================================================
@dataclass
class LinhaInadimplente:
    marca: str
    cnpj: str
    dias_atraso: int
    valor_aberto: float
    bloqueio_atual: str       # 'nenhum' | 'recebimento' | 'total' | 'vendas' | 'acesso'
    classe: str               # 'A' | 'B' | 'C' | '?'
    boletos: int
    pix_cobv: int

    @property
    def cnpj_mascarado(self) -> str:
        d = "".join(filter(str.isdigit, self.cnpj))
        if len(d) != 14:
            return self.cnpj
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


# ============================================================================
# Sugestão de ação por nível de bloqueio
# ============================================================================
def sugerir_acao(linha: LinhaInadimplente) -> str:
    """Retorna a ação recomendada baseada em dias de atraso e valor."""
    d = linha.dias_atraso
    classe = linha.classe
    if d <= 5:
        return "observar (alerta Gmail apenas)"
    if d <= 15 and classe == "A":
        return "alerta + bloqueio_recebimento (nivel 1)"
    if d <= 30:
        return "bloqueio_recebimento (nivel 1)"
    if d <= 45:
        return "bloqueio_total = principal=Nao (nivel 3)"
    if d <= 60:
        return "bloqueio_vendas (nivel 4)"
    return "bloqueio_acesso (nivel 5) URGENTE"


# ============================================================================
# Mock data — exemplo de 5 marcas fictícias
# ============================================================================
def gerar_mock() -> list[LinhaInadimplente]:
    return [
        LinhaInadimplente("Bijoux Estrela",  "12.345.678/0001-90", 45, 3200.00, "nenhum",      "C", 2, 1),
        LinhaInadimplente("Atelier Lua",     "23.456.789/0001-01", 18, 1450.00, "recebimento", "B", 1, 0),
        LinhaInadimplente("Boutique Sol",    "34.567.890/0001-12",  7,  890.00, "nenhum",      "B", 0, 1),
        LinhaInadimplente("Moda Vivace",     "45.678.901/0001-23", 62, 5700.00, "vendas",      "C", 3, 2),
        LinhaInadimplente("Acessorios Mar",  "56.789.012/0001-34",  3,  420.00, "nenhum",      "A", 1, 0),
    ]


# ============================================================================
# Coleta real — junta LivePDV + Efí
# ============================================================================
def coletar_real(dias_min: int = 1, cnpj_filtro: Optional[str] = None) -> list[LinhaInadimplente]:
    """
    Conecta LivePDV + Efí e gera relatório real.
    Requer credenciais em .env (LIVEPDV_*, EFI_*).
    """
    try:
        from livepdv_client import LivePDVClient
        from efi_client import EfiClient
    except ImportError as exc:
        print(f"[ERRO] Modulos nao encontrados: {exc}")
        print("       Verifique se livepdv_client.py e efi_client.py estao no PYTHONPATH")
        sys.exit(2)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    print("[1/4] Conectando ao LivePDV...", end=" ", flush=True)
    lpv = LivePDVClient()
    lpv.login()
    expositores = list(lpv.listar_expositores())
    print(f"OK ({len(expositores)} expositores)")

    print("[2/4] Listando cobrancas vencidas na Efi...", end=" ", flush=True)
    efi = EfiClient()
    inadimplentes = efi.consolidar_todos_inadimplentes(dias_atraso_min=dias_min)
    print(f"OK ({len(inadimplentes)} CNPJs inadimplentes)")

    # Indexa expositores por CNPJ (só dígitos)
    print("[3/4] Cruzando CNPJs LivePDV x Efi...", end=" ", flush=True)
    expo_por_cnpj = {}
    for e in expositores:
        cnpj_d = "".join(filter(str.isdigit, str(e.get("cnpj", ""))))
        if cnpj_d:
            expo_por_cnpj[cnpj_d] = e
    print("OK")

    print("[4/4] Montando relatorio...", end=" ", flush=True)
    linhas: list[LinhaInadimplente] = []
    for cnpj_d, dados in inadimplentes.items():
        if cnpj_filtro and "".join(filter(str.isdigit, cnpj_filtro)) != cnpj_d:
            continue
        expo = expo_por_cnpj.get(cnpj_d, {})
        nome = expo.get("nome") or expo.get("nome_fantasia") or f"CNPJ {cnpj_d}"
        bloq = "nenhum"
        if expo.get("bloqueio_acesso") == "1":
            bloq = "acesso"
        elif expo.get("bloqueio_vendas") == "1":
            bloq = "vendas"
        linhas.append(
            LinhaInadimplente(
                marca=nome,
                cnpj=cnpj_d,
                dias_atraso=dados.get("dias_max", 0) or 0,
                valor_aberto=dados.get("total_aberto", 0.0),
                bloqueio_atual=bloq,
                classe="?",  # classificacao A/B/C precisa de vendas 30d (proximo passo)
                boletos=len(dados.get("boletos", [])),
                pix_cobv=len(dados.get("pix_cobv", [])),
            )
        )
    print(f"OK ({len(linhas)} marcas no relatorio)")
    return linhas


# ============================================================================
# Renderização
# ============================================================================
def imprimir_relatorio(linhas: list[LinhaInadimplente], modo: str) -> None:
    titulo = f"  RELATORIO DE MARCAS INADIMPLENTES — MODO {modo.upper()}  "
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    print()
    print("=" * (len(titulo) + 4))
    print("  " + titulo)
    print("  Gerado em: " + ts)
    print("=" * (len(titulo) + 4))
    print()

    if not linhas:
        print("Nenhuma marca inadimplente encontrada. 🎉")
        return

    # Ordena: maior atraso primeiro
    linhas_ord = sorted(linhas, key=lambda x: (-x.dias_atraso, -x.valor_aberto))

    headers = ["#", "Marca", "CNPJ", "Dias", "Em aberto", "Bloqueio", "Classe", "Acao sugerida"]
    rows = []
    for i, l in enumerate(linhas_ord, 1):
        rows.append([
            i,
            l.marca[:24],
            l.cnpj_mascarado,
            l.dias_atraso,
            f"R$ {l.valor_aberto:>10,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            l.bloqueio_atual,
            l.classe,
            sugerir_acao(l),
        ])
    print(_formatar_tabela(headers, rows))
    print()

    total = sum(l.valor_aberto for l in linhas_ord)
    maior = linhas_ord[0]
    print("RESUMO")
    print(f"  Total inadimplentes:    {len(linhas_ord)} marcas")
    print(f"  Valor total em aberto:  R$ {total:,.2f}")
    print(f"  Maior atraso:           {maior.dias_atraso} dias ({maior.marca})")
    print()


def exportar_csv(linhas: list[LinhaInadimplente], path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "marca", "cnpj", "dias_atraso", "valor_aberto",
            "bloqueio_atual", "classe", "boletos", "pix_cobv", "acao_sugerida",
        ])
        for l in linhas:
            writer.writerow([
                l.marca, l.cnpj_mascarado, l.dias_atraso, f"{l.valor_aberto:.2f}",
                l.bloqueio_atual, l.classe, l.boletos, l.pix_cobv, sugerir_acao(l),
            ])
    print(f"Exportado para: {path}")


# ============================================================================
# CLI
# ============================================================================
def main() -> int:
    p = argparse.ArgumentParser(
        description="Relatorio de marcas inadimplentes (LivePDV + Efi)"
    )
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--mock", action="store_true", help="Usa dados ficticios (sem credenciais)")
    grp.add_argument("--real", action="store_true", help="Conecta LivePDV + Efi reais (precisa .env)")
    p.add_argument("--dias", type=int, default=1, help="Dias minimos de atraso (default=1)")
    p.add_argument("--cnpj", type=str, default=None, help="Filtrar por CNPJ especifico")
    p.add_argument("--csv", action="store_true", help="Exporta CSV em ./relatorios/")
    args = p.parse_args()

    if args.mock:
        linhas = gerar_mock()
        modo = "mock"
    else:
        linhas = coletar_real(dias_min=args.dias, cnpj_filtro=args.cnpj)
        modo = "real"

    imprimir_relatorio(linhas, modo)

    if args.csv:
        data_str = datetime.now().strftime("%Y-%m-%d_%H%M")
        path = f"./relatorios/inadimplentes_{modo}_{data_str}.csv"
        exportar_csv(linhas, path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
