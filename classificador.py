"""
classificador.py
================

Classifica marcas em A / B / C / D segundo a regra do projeto integrador.

Regras de negocio (vendas dos ultimos 30 dias vs aluguel mensal):
  A : vendas_30d >= aluguel              (saudavel)
  B : 50% <= vendas_30d / aluguel < 100% (alerta)
  C : 0  <  vendas_30d / aluguel < 50%   (critico)
  D : vendas_30d == 0                    (silencio)
  ? : aluguel ausente / dados incompletos
"""

from __future__ import annotations

from typing import Optional, Dict, Any


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace("R$", "").replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return None


def classificar(vendas_30d: Any, aluguel: Any) -> str:
    """Devolve 'A', 'B', 'C', 'D' ou '?' conforme a regra do projeto."""
    v = _to_float(vendas_30d)
    a = _to_float(aluguel)

    if a is None or a <= 0:
        return "?"
    if v is None:
        return "?"
    if v == 0:
        return "D"

    ratio = v / a
    if ratio >= 1.0:
        return "A"
    if ratio >= 0.5:
        return "B"
    return "C"


def classificar_marca(marca: Dict[str, Any]) -> Dict[str, Any]:
    """Anota o dict da marca com a classe calculada. Mantem todos os campos
    originais e adiciona 'classe' e 'ratio_vendas_aluguel'."""
    vendas = marca.get("vendas_30d")
    aluguel = marca.get("aluguel")
    classe = classificar(vendas, aluguel)
    v = _to_float(vendas) or 0.0
    a = _to_float(aluguel) or 0.0
    ratio = (v / a) if a > 0 else 0.0
    out = dict(marca)
    out["classe"] = classe
    out["ratio_vendas_aluguel"] = round(ratio, 4)
    return out


if __name__ == "__main__":
    casos = [
        {"nome": "X", "vendas_30d": 1500, "aluguel": 1000},  # A
        {"nome": "Y", "vendas_30d": 700,  "aluguel": 1000},  # B
        {"nome": "Z", "vendas_30d": 300,  "aluguel": 1000},  # C
        {"nome": "W", "vendas_30d": 0,    "aluguel": 1000},  # D
        {"nome": "Q", "vendas_30d": 500,  "aluguel": None},  # ?
    ]
    for c in casos:
        print(classificar_marca(c))
