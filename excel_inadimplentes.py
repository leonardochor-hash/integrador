"""
excel_inadimplentes.py
======================

Leitor de planilha Excel exportada do painel da Efí (Receber > Gestão de
cobranças > Boletos > Exportar).

Estrutura esperada da planilha (cabeçalho na linha 1):

    Loja | Número da Cobrança | Valor (R$) | Status | Data de Emissão |
    Forma de Cobrança | Itens | Nome | E-mail | Telefone | Documento |
    Data de Vencimento | Valor Pago | Pago Em

Apenas linhas com Status = "Inadimplente" são consideradas. Status
"Cancelado", "Pago", "Aguardando" e "Marcado como pago" são ignorados.

Saída: lista de dicts no MESMO formato usado pelo efi_client.py para que
o relatorio_inadimplentes.py possa consumir indistintamente:

    {
        "cnpj": "12345678000100",            # só dígitos
        "nome": "Razão social",
        "valor": 990.00,                      # float em reais
        "vencimento": "2026-05-20",          # ISO YYYY-MM-DD
        "dias_atraso": 1,
        "numero_cobranca": "1013504771",
        "fonte": "excel",
    }
"""

from __future__ import annotations

import re
from datetime import datetime, date
from pathlib import Path
from typing import Iterable, List, Dict, Any, Optional


STATUS_INADIMPLENTES = {"inadimplente", "vencido", "atrasado"}


def _so_digitos(valor: Any) -> str:
    if valor is None:
        return ""
    return re.sub(r"\D", "", str(valor))


def _para_float(valor: Any) -> float:
    if valor is None or valor == "":
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip()
    # Formatos comuns: "1.190,00" "1190,00" "1190.00" "R$ 1.190,00"
    s = s.replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _para_iso(valor: Any) -> Optional[str]:
    if valor is None or valor == "":
        return None
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%Y-%m-%d")
    s = str(valor).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _dias_atraso(venc_iso: Optional[str]) -> int:
    if not venc_iso:
        return 0
    try:
        v = datetime.strptime(venc_iso, "%Y-%m-%d").date()
    except ValueError:
        return 0
    delta = (date.today() - v).days
    return max(0, delta)


def carregar_inadimplentes(caminho: str | Path) -> List[Dict[str, Any]]:
    """Lê o .xlsx e devolve apenas inadimplentes normalizados."""
    try:
        import openpyxl
    except ImportError as e:
        raise RuntimeError(
            "openpyxl não instalado. Rode: pip install openpyxl"
        ) from e

    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Planilha não encontrada: {caminho}")

    wb = openpyxl.load_workbook(caminho, data_only=True, read_only=True)
    ws = wb.active

    rows = ws.iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(rows)]

    # Mapa: nome de coluna esperado -> índice
    def idx(nome: str) -> Optional[int]:
        nome_low = nome.lower()
        for i, h in enumerate(header):
            if h.lower().strip() == nome_low:
                return i
        return None

    i_loja = idx("Loja")
    i_num = idx("Número da Cobrança")
    i_valor = idx("Valor (R$)")
    i_status = idx("Status")
    i_emissao = idx("Data de Emissão")
    i_nome = idx("Nome")
    i_email = idx("E-mail")
    i_tel = idx("Telefone")
    i_doc = idx("Documento")
    i_venc = idx("Data de Vencimento")

    out: List[Dict[str, Any]] = []
    for row in rows:
        if row is None or all(c is None for c in row):
            continue
        status = str(row[i_status]).strip().lower() if i_status is not None and row[i_status] else ""
        if status not in STATUS_INADIMPLENTES:
            continue

        cnpj = _so_digitos(row[i_doc] if i_doc is not None else "")
        if not cnpj:
            continue

        venc_iso = _para_iso(row[i_venc]) if i_venc is not None else None
        nome = str(row[i_nome]).strip() if i_nome is not None and row[i_nome] else ""
        valor = _para_float(row[i_valor]) if i_valor is not None else 0.0
        num = str(row[i_num]).strip() if i_num is not None and row[i_num] else ""

        out.append({
            "cnpj": cnpj,
            "nome": nome,
            "valor": valor,
            "vencimento": venc_iso,
            "dias_atraso": _dias_atraso(venc_iso),
            "numero_cobranca": num,
            "loja": str(row[i_loja]).strip() if i_loja is not None and row[i_loja] else "",
            "email": str(row[i_email]).strip() if i_email is not None and row[i_email] else "",
            "telefone": str(row[i_tel]).strip() if i_tel is not None and row[i_tel] else "",
            "fonte": "excel",
        })

    wb.close()
    return out


def consolidar_por_cnpj(itens: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Agrupa boletos pelo CNPJ — soma valor_aberto e pega dias_max."""
    agreg: Dict[str, Dict[str, Any]] = {}
    for c in itens:
        cnpj = c["cnpj"]
        entry = agreg.setdefault(cnpj, {
            "cnpj": cnpj,
            "nome": c.get("nome", ""),
            "boletos": [],
            "total_aberto": 0.0,
            "dias_max": 0,
        })
        entry["boletos"].append(c)
        entry["total_aberto"] += float(c.get("valor") or 0.0)
        entry["dias_max"] = max(entry["dias_max"], int(c.get("dias_atraso") or 0))
        if not entry["nome"]:
            entry["nome"] = c.get("nome", "")
    return agreg


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("uso: python excel_inadimplentes.py arquivo.xlsx")
        sys.exit(1)
    inad = carregar_inadimplentes(sys.argv[1])
    print(f"[excel_inadimplentes] {len(inad)} inadimplentes carregados")
    print(json.dumps(consolidar_por_cnpj(inad), indent=2, ensure_ascii=False, default=str)[:3000])
