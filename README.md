# integrador

Integrador Python para classificar marcas inadimplentes no **LivePDV / Moombox** e acionar bloqueios automatizados em diferentes niveis de severidade.

## Stack de integracao prevista

- **LivePDV / Moombox** (origem das vendas reais e ponto de aplicacao dos bloqueios)
- **Efi / Asaas** (cobrancas e conciliacao financeira)
- **Airtable** (dashboard / base de dados de marcas e contratos)
- **Zoho** (CRM)
- **Gmail** (notificacoes automatizadas)

## Estrategia

A linha dorsal e o LivePDV. Partimos das vendas reais dos ultimos 30 dias para descobrir as marcas ativas, depois conciliamos com cobrancas (Efi/Asaas) e cadastramos/atualizamos no Airtable.

### Regras de classificacao (por marca/loja)

| Classificacao | Criterio |
|---------------|----------|
| Marca A | vendas 30d > valor do aluguel |
| Marca B | vendas 30d entre 50% e 100% do aluguel |
| Marca C | vendas 30d < 50% do aluguel |

### Escala de bloqueio (acoes automatizadas no LivePDV)

| Classificacao | Acao |
|---------------|------|
| Marca A | Nenhuma |
| Marca B | `bloqueio_recebimento=1` (Zoop, leve) |
| Marca C | `principal=0` (Zoop, repasse total) |
| Atraso grave | `Fornecedores[bloqueio_vendas]=1` (nao vende mais) |
| Inadimplencia critica | `Fornecedores[bloqueio_acesso]=1` (nao loga mais) |

## Estrutura do projeto

```
integrador/
|- README.md
|- requirements.txt
|- .env.example          # template - copie para .env e preencha
|- .gitignore
|- livepdv_client.py     # cliente HTTP autenticado contra LivePDV
`- docs/
   `- livepdv_endpoints.md   # mapa completo dos endpoints
```

## Como rodar

1. Clone o repositorio
   ```bash
   git clone https://github.com/leonardochor-hash/integrador.git
   cd integrador
   ```

2. Crie um virtualenv e instale as dependencias
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Linux/Mac
   # ou .venv\Scripts\activate    # Windows
   pip install -r requirements.txt
   ```

3. Configure as credenciais
   ```bash
   cp .env.example .env
   # edite .env com suas credenciais
   ```

4. Teste a conexao (lista 1a pagina da Zoop, sem alterar nada)
   ```bash
   python livepdv_client.py
   ```

## Uso programatico

```python
from livepdv_client import LivePDVClient
import os

with LivePDVClient() as client:
    client.login(os.environ["LIVEPDV_USERNAME"],
                 os.environ["LIVEPDV_PASSWORD"])

    # Listar (somente leitura)
    empresas = client.listar_zoop_empresas()
    fornecedores = client.listar_fornecedores()

    # Bloqueios - usar com cautela
    # Marca B (atraso leve):
    client.bloquear_recebimento_zoop(zoop_id=1826, ativar=True)

    # Marca C (atraso grave):
    client.bloquear_repasse_total(zoop_id=1826, ativar=True)

    # Casos severos (so via tela Expositores):
    client.bloquear_vendas_expositor(fornecedor_id=736, ativar=True)
    client.bloquear_acesso_expositor(fornecedor_id=736, ativar=True)

    # Desbloqueio: passe ativar=False
    client.bloquear_recebimento_zoop(zoop_id=1826, ativar=False)
```

## Documentacao tecnica

Veja [`docs/livepdv_endpoints.md`](docs/livepdv_endpoints.md) para o mapa completo de endpoints, payloads e CSRF.

## Seguranca

- **Nunca commite o arquivo `.env`** (ja esta no `.gitignore` via padrao `env*`).
- O cliente usa exclusivamente credenciais lidas de variaveis de ambiente.
- O CSRF token e renovado dinamicamente antes de cada operacao sensivel.
- Funcoes de bloqueio sao idempotentes: chamar com mesmo valor varias vezes nao causa efeito colateral.

## Roadmap

- [x] Cliente LivePDV com 5 niveis de bloqueio
- [ ] Cliente Airtable (cadastro de marcas + status financeiro)
- [ ] Cliente Efi (cobrancas)
- [ ] Cliente Asaas (cobrancas)
- [ ] Cliente Gmail (notificacoes)
- [ ] Orquestrador (`runner.py`) - classifica + aplica bloqueios + notifica
- [ ] Cron / GitHub Actions para execucao agendada
- [ ] Testes automatizados

## Status

Em desenvolvimento. Estagio atual: **cliente LivePDV funcional com mapa completo de endpoints de bloqueio**.

