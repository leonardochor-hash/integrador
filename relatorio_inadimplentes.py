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
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from classificador import classificar


# ============================================================================
# Tabela: usa 'tabulate' se disponível, senão fallback puro
# ============================================================================
try:
    from tabulate import tabulate  # type: ignore

    _HAS_TABULATE = True
except ImportError:
    _HAS_TABULATE = False


def _formatar_tabela(headers, linhas):
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
    bloqueio_atual: str
    classe: str
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
# Mock data
# ============================================================================
def gerar_mock():
    return [
        LinhaInadimplente("Bijoux Estrela",  "12.345.678/0001-90", 45, 3200.00, "nenhum",      "C", 2, 1),
        LinhaInadimplente("Atelier Lua",     "23.456.789/0001-01", 18, 1450.00, "recebimento", "B", 1, 0),
        LinhaInadimplente("Boutique Sol",    "34.567.890/0001-12",  7,  890.00, "nenhum",      "B", 0, 1),
        LinhaInadimplente("Moda Vivace",     "45.678.901/0001-23", 62, 5700.00, "vendas",      "C", 3, 2),
        LinhaInadimplente("Acessorios Mar",  "56.789.012/0001-34",  3,  420.00, "nenhum",      "A", 1, 0),
    ]


# ============================================================================
# Coleta real
# ============================================================================
def coletar_real(dias_min: int = 1, cnpj_filtro: Optional[str] = None):
    """
    Conecta LivePDV + Efí.
    Requer variáveis de ambiente:
      LIVEPDV_BASE_URL, LIVEPDV_USERNAME, LIVEPDV_PASSWORD
      EFI_CLIENT_ID, EFI_CLIENT_SECRET, EFI_PIX_CERT_PATH (opcional)
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

    # Lê credenciais do env (já populadas pelo Colab ou .env)
    lpv_user = os.environ.get("LIVEPDV_USERNAME")
    lpv_pass = os.environ.get("LIVEPDV_PASSWORD")
    lpv_base = os.environ.get("LIVEPDV_BASE_URL", "https://expositores.moombox.com.br")
    if not lpv_user or not lpv_pass:
        print("[ERRO] LIVEPDV_USERNAME ou LIVEPDV_PASSWORD nao definidos no ambiente.")
        sys.exit(3)

    expositores = []
    # ------------------------- LivePDV -------------------------
    print("[1/4] Conectando ao LivePDV...", end=" ", flush=True)
    try:
        lpv = LivePDVClient(base_url=lpv_base)
        # tentar várias assinaturas de login para máxima compatibilidade
        try:
            lpv.login(lpv_user, lpv_pass)
        except TypeError:
            try:
                lpv.login(username=lpv_user, password=lpv_pass)
            except TypeError:
                lpv.login()  # versão antiga lia do env

        # listar expositores via método disponível
        if hasattr(lpv, "listar_expositores"):
            expositores = list(lpv.listar_expositores())
        elif hasattr(lpv, "list_expositores"):
            expositores = list(lpv.list_expositores())
        elif hasattr(lpv, "listar_fornecedores"):
            expositores = list(lpv.listar_fornecedores())
        else:
            print("AVISO: metodo de listagem de expositores nao encontrado")
            expositores = []
        print(f"OK ({len(expositores)} expositores)")
    except Exception as exc:
        print(f"FALHOU")
        print(f"      ! {type(exc).__name__}: {exc}")
        print(f"      ! Continuando sem dados do LivePDV (nomes de marca virao como 'CNPJ XXX')")

    # ------------------------- Efí -------------------------
    inadimplentes = {}
    print("[2/4] Listando cobrancas vencidas na Efi...", end=" ", flush=True)
    try:
        efi = EfiClient()
        inadimplentes = efi.consolidar_todos_inadimplentes(dias_atraso_min=dias_min)
        print(f"OK ({len(inadimplentes)} CNPJs inadimplentes)")
    except Exception as exc:
        print("FALHOU")
        print(f"      ! {type(exc).__name__}: {exc}")
        print("      ! Verifique credenciais EFI_CLIENT_ID / EFI_CLIENT_SECRET / EFI_PIX_CERT_PATH")
        # ainda retorna vazio pra nao crashar
        return []

    # ------------------------- Cruzamento -------------------------
    print("[3/4] Cruzando CNPJs LivePDV x Efi...", end=" ", flush=True)
    expo_por_cnpj = {}
    for e in expositores:
        # tolerância a vários formatos de dict
        cnpj_raw = e.get("cnpj") if isinstance(e, dict) else None
        if not cnpj_raw and isinstance(e, dict):
            cnpj_raw = e.get("CNPJ") or e.get("documento")
        cnpj_d = "".join(filter(str.isdigit, str(cnpj_raw or "")))
        if cnpj_d:
            expo_por_cnpj[cnpj_d] = e
    print("OK")

    # ------------------------- Montagem -------------------------
    print("[4/4] Montando relatorio...", end=" ", flush=True)
    linhas = []
    for cnpj_d, dados in inadimplentes.items():
        if cnpj_filtro and "".join(filter(str.isdigit, cnpj_filtro)) != cnpj_d:
            continue
        expo = expo_por_cnpj.get(cnpj_d, {}) or {}
        nome = (
            (expo.get("nome") if isinstance(expo, dict) else None)
            or (expo.get("nome_fantasia") if isinstance(expo, dict) else None)
            or f"CNPJ {cnpj_d}"
        )
        bloq = "nenhum"
        if isinstance(expo, dict):
            if str(expo.get("bloqueio_acesso", "")) == "1":
                bloq = "acesso"
            elif str(expo.get("bloqueio_vendas", "")) == "1":
                bloq = "vendas"
        linhas.append(
            LinhaInadimplente(
                marca=nome,
                cnpj=cnpj_d,
                dias_atraso=int(dados.get("dias_max", 0) or 0),
                valor_aberto=float(dados.get("total_aberto", 0.0)),
                bloqueio_atual=bloq,
                classe=classificar(dados.get("vendas_30d"), dados.get("aluguel")),
                boletos=len(dados.get("boletos", [])),
                pix_cobv=len(dados.get("pix_cobv", [])),
            )
        )
    print(f"OK ({len(linhas)} marcas no relatorio)")
    return linhas


# ============================================================================
# Renderização
# ============================================================================
def imprimir_relatorio(linhas, modo):
    titulo = f"  RELATORIO DE MARCAS INADIMPLENTES — MODO {modo.upper()}  "
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    print()
    print("=" * (len(titulo) + 4))
    print("  " + titulo)
    print("  Gerado em: " + ts)
    print("=" * (len(titulo) + 4))
    print()

    if not linhas:
        print("Nenhuma marca inadimplente encontrada (ou erro na coleta).")
        return

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


def exportar_csv(linhas, path):
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
def main():
    p = argparse.ArgumentParser(description="Relatorio de marcas inadimplentes (LivePDV + Efi)")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--mock", action="store_true")
    grp.add_argument("--real", action="store_true")
    p.add_argument("--dias", type=int, default=1)
    p.add_argument("--cnpj", type=str, default=None)
    p.add_argument("--csv", action="store_true")
    args = p.parse_args()

    if args.mock:
        linhas = gerar_mock()
        modo = "mock"
    else:
        try:
            linhas = coletar_real(dias_min=args.dias, cnpj_filtro=args.cnpj)
        except Exception:
            print("\n[ERRO FATAL] Algo deu errado na coleta:")
            traceback.print_exc()
            linhas = []
        modo = "real"

    imprimir_relatorio(linhas, modo)

    if args.csv and linhas:
        data_str = datetime.now().strftime("%Y-%m-%d_%H%M")
        path = f"./relatorios/inadimplentes_{modo}_{data_str}.csv"
        exportar_csv(linhas, path)

    return 0


if __name__ == "__main__":
    sys.exit(main())

