"""
classificador.py
================

Classifica marcas em A / B / C / D segundo a regra do projeto integrador.

Regras de negocio:
  A : vendas_30d >= aluguel              (saudavel)
  B : 50% <= vendas_30d/aluguel < 100%   (alerta)
