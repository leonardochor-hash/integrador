# Efí — Endpoints utilizados pelo integrador

> Mapeamento dos endpoints da Efí (antiga Gerencianet) consumidos pelo módulo `efi_client.py`.
> Documentação oficial: https://dev.efipay.com.br/docs/

A Efí expõe **duas APIs distintas** que o integrador combina para detectar inadimplência completa:

| API | Tipo de cobrança | Base URL produção | Autenticação |
|---|---|---|---|
| **Pagamentos** | Boletos, carnês, links de pagamento | `https://api.gerencianet.com.br` | Basic Auth → Bearer |
| **PIX** | Cobranças PIX (imediatas + com vencimento) | `https://pix.api.efipay.com.br` | OAuth2 + **mTLS** (certificado) |

---

## 1) Como obter credenciais

1. Acesse o painel: https://app.efipay.com.br
2. Menu lateral → **API** → **Minhas Aplicações**
3. Crie (ou abra) uma aplicação habilitando os escopos necessários:
   - **Pagamentos**: `boletos.read`, `carnes.read`, `charges.read`
   - **PIX**: `cob.read`, `cobv.read`, `pix.read`
4. Copie **Client_Id** e **Client_Secret** (produção) → vão no `.env`
5. **Apenas para PIX**: baixe o certificado `.p12` no painel da aplicação

### Convertendo .p12 → .pem

A biblioteca `requests` do Python prefere `.pem`. Converta com OpenSSL:

```bash
# Gera um único .pem com certificado + chave privada
openssl pkcs12 -in efi-prod.p12 -out efi-prod.pem -nodes
# (Pressione Enter na senha se vazia)
```

Salve em `./certs/efi-prod.pem` e referencie em `EFI_PIX_CERT_PATH`.

---

## 2) Endpoints — Efí Pagamentos

### POST /oauth/token
Gera token de acesso. Body: `{"grant_type":"client_credentials"}`. Header: `Authorization: Basic <base64(id:secret)>`.

Resposta:
```json
{"access_token": "...", "token_type": "Bearer", "expires_in": 3600}
```

### GET /v1/charges
Lista cobranças (boletos/carnês). Query params suportados:

| Param | Tipo | Descrição |
|---|---|---|
| `limit` | int | Itens por página (máx ~100) |
| `offset` | int | Deslocamento |
| `status` | string | `new`, `waiting`, `paid`, `unpaid`, `refunded`, `expired` |
| `vencimento_de` | YYYY-MM-DD | Data de vencimento inicial |
| `vencimento_ate` | YYYY-MM-DD | Data de vencimento final |

Estrutura de cada item (campos relevantes para o integrador):

```json
{
  "charge_id": 123456,
  "status": "unpaid",
  "total": 25000,
  "expire_at": "2025-10-15",
  "customer": {
    "juridical_person": {
      "corporate_number": "00000000000000",
      "corporate_name": "EMPRESA EXEMPLO LTDA"
    }
  }
}
```

> ⚠️ `total` vem em **centavos**.
> ⚠️ Para PJ, o CNPJ está em `customer.juridical_person.corporate_number`.

### GET /v1/charge/:id
Detalhe de uma cobrança específica.

### GET /v1/charge/:id/history
Histórico de eventos (criação, vencimento, baixa, pagamento).

---

## 3) Endpoints — Efí PIX

### POST /oauth/token
Idêntico ao Pagamentos, **mas exige certificado mTLS** na requisição.

### GET /v2/cob
Lista cobranças PIX imediatas (sem vencimento). Query params:

| Param | Descrição |
|---|---|
| `inicio` | Data ISO 8601 UTC (ex: `2025-04-21T00:00:00Z`) |
| `fim` | Data ISO 8601 UTC |
| `cpf` ou `cnpj` | Filtro por devedor |
| `status` | `ATIVA`, `CONCLUIDA`, `REMOVIDA_PELO_USUARIO_RECEBEDOR` |
| `paginacao.paginaAtual` | int |
| `paginacao.itensPorPagina` | int (máx 1000) |

### GET /v2/cobv
**Cobranças PIX com vencimento** — análogas a boletos PIX. **Esta é a API mais útil para detectar inadimplência PIX.**

Mesmos params de `/v2/cob`, mais campos de vencimento na resposta:

```json
{
  "calendario": {
    "dataDeVencimento": "2025-09-30",
    "validadeAposVencimento": 30
  },
  "txid": "abc123...",
  "revisao": 0,
  "devedor": {
    "cnpj": "00000000000000",
    "nome": "EMPRESA EXEMPLO LTDA"
  },
  "valor": {
    "original": "150.00"
  },
  "status": "ATIVA"
}
```

> ⚠️ `valor.original` é **string em reais com 2 decimais** (ex: `"150.00"`).
> ⚠️ `status: "ATIVA"` + vencimento passado = inadimplente.

### GET /v2/pix
PIX recebidos (úteis para conciliação).

---

## 4) Critérios de inadimplência usados pelo integrador

O método `EfiClient.consolidar_todos_inadimplentes()` aplica:

| Fonte | Critério |
|---|---|
| Boletos (`/v1/charges`) | `status in ("unpaid","expired")` AND `expire_at <= hoje - EFI_DIAS_ATRASO_MIN` |
| PIX cobv (`/v2/cobv`) | `status == "ATIVA"` AND `dataDeVencimento <= hoje - EFI_DIAS_ATRASO_MIN` |

Variável `EFI_DIAS_ATRASO_MIN` (default `1`) define o limiar de dias após o vencimento.

### Cruzamento com Airtable

A chave de junção entre Efí e Airtable/LivePDV é o **CNPJ (somente dígitos)**:

```
Boleto:  customer.juridical_person.corporate_number  ->  só dígitos
Cob_v:   devedor.cnpj                                 ->  só dígitos
```

A função `EfiClient._so_digitos()` normaliza qualquer CNPJ removendo pontuação.

---

## 5) Limites e cuidados

- **Rate limit**: respeitado pelo `requests.Session()` reutilizado.
- **Token expira em 1h** → cache local com refresh automático em `_get_token()`.
- **mTLS**: sem o certificado, qualquer chamada PIX retorna **401**.
- **Sandbox PIX**: `https://pix-h.api.efipay.com.br` (homologação).
- **Sandbox Pagamentos**: `https://sandbox.gerencianet.com.br`.
- **Logs**: nunca logar `access_token` nem `client_secret`.

---

## 6) Roadmap

- [ ] Webhook receiver para `/v2/webhook` (notificação push de PIX pago) — fora do escopo do MVP.
- [ ] Cache em disco dos resultados de `consolidar_todos_inadimplentes()` para reduzir chamadas.
- [ ] Retry com backoff em 429/5xx.
