# integrador

Integrador Python para classificar marcas inadimplentes no **LivePDV / Moombox** e acionar bloqueios automatizados em diferentes niveis de severidade.

## Stack de integracao prevista

- **LivePDV / Moombox** (origem das vendas reais e ponto de aplicacao dos bloqueios) — ✅ implementado
- **Efí / Asaas** (cobrancas e conciliacao financeira) — ✅ Efí implementado · Asaas pendente
- **Airtable** (dashboard / base de dados de marcas e contratos) — ⏳ pendente
- **Zoho** (CRM) — ⏳ pendente
- **Gmail** (notificacoes automatizadas) — ⏳ pendente

## Estrategia

A linha dorsal e o LivePDV. Partimos das vendas reais dos ultimos 30 dias para descobrir as marcas ativas, depois conciliamos com cobrancas (Efi/Asaas) e cadastramos/atualizamos no Airtable.

### Regras de classificacao (por marca/loja)

| Classificacao | Criterio |
|---------------|----------|
| Marca A | vendas 30d > valor do aluguel |
| Marca B | vendas 30d entre 50% e 100% do aluguel |
| Marca C | vendas 30d < 50% do aluguel |

### Escala de bloqueio (acoes automatizadas no LivePDV)

| Nivel | Acao | Endpoint / Campo |
|-------|------|------------------|
| 1 — Recebimento (leve) | Trava repasse do Zoop | `POST /zoop/cadastro-zoop/inline-update` · `bloqueio_recebimento=1` |
| 2 — Politica detalhada | Salva politica customizada | `POST /zoop/cadastro-zoop/save-policy` |
| 3 — Repasse total | Marca `Principal = Nao` | `POST /zoop/cadastro-zoop/inline-update` · `principal=0` |
| 4 — Bloqueio de vendas | Marca campo no expositor | `POST /configura/fornecedores/update` · `bloqueio_vendas=1` |
| 5 — Bloqueio de acesso | Trava login do expositor | `POST /configura/fornecedores/update` · `bloqueio_acesso=1` |

## Modulos disponiveis

### `livepdv_client.py`
Cliente HTTP autenticado para o LivePDV (Yii2 + PJAX). Faz login com CSRF, lista expositores, lista marcas no cadastro Zoop, executa os 5 niveis de bloqueio descritos acima e tem helpers para cruzar expositor ↔ marca.

### `efi_client.py`
Cliente unificado para as APIs da Efí:

- `EfiPagamentosClient` — boletos/carnês via Basic Auth (`/v1/charges`)
- `EfiPixClient` — cobrancas PIX via OAuth2 + mTLS (`/v2/cob`, `/v2/cobv`)
- `EfiClient` (wrapper) — consolida ambas e expoe `listar_inadimplentes_por_cnpj()` e `consolidar_todos_inadimplentes()` cruzando por CNPJ.

Documentacao detalhada: [`docs/efi_endpoints.md`](docs/efi_endpoints.md).

### `relatorio_inadimplentes.py`
Script CLI que une LivePDV + Efí e gera tabela consolidada das marcas inadimplentes.

```bash
# Visualizar formato com dados ficticios (nao precisa credenciais)
python relatorio_inadimplentes.py --mock

# Rodar com dados reais (precisa .env configurado)
python relatorio_inadimplentes.py --real

# Filtros e exportacao
python relatorio_inadimplentes.py --real --dias 7 --csv
python relatorio_inadimplentes.py --real --cnpj 12345678000190
```

**Exemplo de saida (mock):**

```
+----+--------------------+--------------------+------+--------------+--------------+--------+---------------------------------+
| #  | Marca              | CNPJ               | Dias | Em aberto    | Bloqueio     | Classe | Acao sugerida                   |
+----+--------------------+--------------------+------+--------------+--------------+--------+---------------------------------+
| 1  | Moda Vivace        | 45.678.901/0001-23 |   62 | R$ 5.700,00  | vendas       | C      | bloqueio_acesso (nivel 5) URGEN |
| 2  | Bijoux Estrela     | 12.345.678/0001-90 |   45 | R$ 3.200,00  | nenhum       | C      | bloqueio_total = principal=Nao  |
| 3  | Atelier Lua        | 23.456.789/0001-01 |   18 | R$ 1.450,00  | recebimento  | B      | bloqueio_recebimento (nivel 1)  |
| 4  | Boutique Sol       | 34.567.890/0001-12 |    7 | R$   890,00  | nenhum       | B      | observar (alerta Gmail apenas)  |
| 5  | Acessorios Mar     | 56.789.012/0001-34 |    3 | R$   420,00  | nenhum       | A      | observar (alerta Gmail apenas)  |
+----+--------------------+--------------------+------+--------------+--------------+--------+---------------------------------+

RESUMO
  Total inadimplentes:    5 marcas
  Valor total em aberto:  R$ 11.660,00
  Maior atraso:           62 dias (Moda Vivace)
```

A sugestao de acao e calculada por `sugerir_acao()`:

| Dias atraso | Acao recomendada |
|-------------|------------------|
| 0–5         | observar (alerta Gmail apenas) |
| 6–15 (A)    | alerta + bloqueio_recebimento (nivel 1) |
| 6–30        | bloqueio_recebimento (nivel 1) |
| 31–45       | bloqueio_total — principal=Nao (nivel 3) |
| 46–60       | bloqueio_vendas (nivel 4) |
| 60+         | bloqueio_acesso (nivel 5) URGENTE |

## Setup

```bash
# 1. Clonar
git clone https://github.com/leonardochor-hash/integrador.git
cd integrador

# 2. Ambiente virtual
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate     # Windows

# 3. Dependencias
pip install -r requirements.txt

# 4. Configurar credenciais
cp .env.example .env
# Edite .env com suas credenciais reais

# 5. Ver relatorio com dados ficticios
python relatorio_inadimplentes.py --mock

# 6. Quando tiver credenciais Efi
python relatorio_inadimplentes.py --real --csv
```

## Estrutura

```
integrador/
├── .env.example                  # template de variaveis de ambiente
├── .gitignore                    # ignora .env, .venv, certs/, __pycache__
├── requirements.txt              # requests, beautifulsoup4, lxml, python-dotenv, tabulate
├── README.md                     # este arquivo
├── livepdv_client.py             # cliente LivePDV/Moombox
├── efi_client.py                 # cliente Efí (Pagamentos + PIX)
├── relatorio_inadimplentes.py    # CLI: une LivePDV + Efí em tabela consolidada
└── docs/
    ├── livepdv_endpoints.md      # mapeamento dos 11 endpoints LivePDV
    └── efi_endpoints.md          # mapeamento das 2 APIs Efí
```

## Seguranca

- ✅ Nenhuma credencial commitada (`.env` no `.gitignore`)
- ✅ `.env.example` apenas com placeholders
- ✅ Certificado PIX fora do repo (`./certs/` ignorado)
- ✅ Nenhum dado real (CNPJ/nome/ID) nos arquivos de documentacao

## Roadmap

- [x] livepdv_client.py (login, listagens, 5 niveis de bloqueio)
- [x] efi_client.py (Pagamentos + PIX, deteccao de inadimplencia por CNPJ)
- [x] relatorio_inadimplentes.py (CLI com modo mock e real)
- [ ] airtable_client.py (CRUD da base de marcas, upsert por nome_fantasia)
- [ ] asaas_client.py (segunda fonte de cobrancas)
- [ ] gmail_notifier.py (envio de alertas)
- [ ] zoho_client.py (CRM)
- [ ] runner.py (orquestrador: vendas → classificacao → bloqueios → notificacao)
- [ ] GitHub Actions (cron diario)

## Licenca

Privado / uso interno.

