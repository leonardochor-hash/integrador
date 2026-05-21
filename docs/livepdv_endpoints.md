# Mapeamento de Endpoints - LivePDV / Moombox (Yii2)

> Documentacao gerada em conjunto com a inspecao manual da plataforma.
> Stack identificada: Yii2 + PJAX + Krajee GridView + Bootstrap 3.
> Autenticacao: cookie `PHPSESSID`.
> CSRF: meta `name="csrf-token"` (88 chars), enviado no campo `_csrf`.

Dominio: `expositores.moombox.com.br`

---

## FLUXO 1 - LOGIN

```
GET  /user/login
POST /user/login        form id="login-form"
Payload:
  _csrf=<TOKEN>                          # 88 chars
  login-form[login]=<USERNAME>
  login-form[password]=<PASSWORD>
  login-form[rememberMe]=0|1             # opcional
Sucesso: redirect 302 para / (home Live PDV) + cookie PHPSESSID
Logout: POST /user/logout (com _csrf)
```

## FLUXO 2 - EXPOSITOR <-> MARCA

Chave de juncao: `nome_fantasia` (texto exato).
O "Nome do Expositor" em relatorios e identico ao "Nome da Marca" no cadastro.

## FLUXO 3 - CADASTRO DETALHADO DE MARCA

```
LISTAGEM (pre-contratos):
  GET  /boxstore/cadastro            (1.061 itens)
  Filtro: CadastroSearch[nome_fantasia]
  PJAX: #kv-grid-cadastro-pjax

DETALHE:
  GET  /boxstore/cadastro/update?id={ID}
  Campos: razao social, nome_fantasia, CNPJ/CPF, contato, endereco,
          email, instagram, departamento, fabricacao propria
```

## FLUXO 4 - NIVEIS DE BLOQUEIO

Existem **DUAS telas** de bloqueio com finalidades distintas:

| Tela | Finalidade |
|------|-----------|
| `/zoop/cadastro-zoop/list-empresas` | Bloqueio de REPASSE (Zoop) |
| `/configura/fornecedores/index` | Bloqueio de ACESSO/VENDAS |

### 4.1 - Tela Zoop (Politica de Repasse)

```
GET  /zoop/cadastro-zoop/list-empresas    (1.653 itens)
Colunas-chave: id, zoopid, status, tipo, nome, cpf_cnpj,
               nome_fantasia, usuario, principal,
               bloqueio_recebimento, marketplace_id
```

**Nivel leve - toggle inline Bloqueio Recebimento:**

```
POST /zoop/cadastro-zoop/inline-update
  _csrf=<TOKEN>
  hasEditable=1
  editableIndex=0
  editableKey={ID_LINHA}
  editableAttribute=bloqueio_recebimento
  CadastroZoop[0][bloqueio_recebimento]=1|0   # 1=bloqueia, 0=libera
```

**Nivel medio - modal do clipe (politica detalhada):**

```
GET  /zoop/cadastro-zoop/load-form-policy?id={ID_LINHA}
POST /zoop/cadastro-zoop/save-policy
Console log: "Politica de Recebimento Atualizad com Sucesso."
```

**Nivel alto - toggle Principal (bloqueio TOTAL de repasse):**

```
POST /zoop/cadastro-zoop/inline-update
  _csrf=<TOKEN>
  hasEditable=1
  editableIndex=0
  editableKey={ID_LINHA}
  editableAttribute=principal
  CadastroZoop[0][principal]=0    # 0 = bloqueio total, 1 = libera
```

### 4.2 - Tela Expositores (Bloqueio de Acesso/Vendas)

```
GET  /configura/fornecedores/index    (1.266 itens)
Colunas: ID, Codigo, CNPJ, Nome, Celular, Email, Tam.Etiquetas,
         Bloqueio_de_acesso (Sim/Nao), Bloqueio_de_vendas (Sim/Nao),
         Usuario

DETALHE:
  GET  /configura/fornecedores/view?id={ID}     # visualizar
  GET  /configura/fornecedores/update?id={ID}   # editar

SAVE:
POST /configura/fornecedores/update?id={ID}    form id="w0"
Payload completo (form-urlencoded):
  _csrf=<TOKEN>                                 # 88 chars
  Fornecedores[codigo]=<CODIGO>
  Fornecedores[nome]=<NOME>
  Fornecedores[telefone]=<FONE>
  Fornecedores[cnpj]=<CNPJ>
  Fornecedores[sheet_size]=<TAM_ETIQUETA>
  Fornecedores[f_user]=<USUARIO_ID>
  Fornecedores[bloqueio_acesso]=0               # hidden default
  Fornecedores[bloqueio_acesso]=1               # checkbox (se marcado)
  Fornecedores[bloqueio_vendas]=0
  Fornecedores[bloqueio_vendas]=1
  + chaves por loja:
    Fornecedores[chave_integracao_<LOJA>]
    Fornecedores[chave_autenticacao_<LOJA>]
Sucesso: 302 redirect para /configura/fornecedores/index
```

**Semantica:**
- `bloqueio_acesso = 1` -> expositor nao consegue mais entrar no portal
- `bloqueio_vendas = 1` -> expositor pode entrar mas nao pode vender

> **ATENCAO:** o POST exige TODOS os campos do form. Estrategia segura:
> 1. GET /configura/fornecedores/update?id={ID}
> 2. Parsear todos os values atuais + _csrf
> 3. Modificar somente bloqueio_acesso / bloqueio_vendas
> 4. POST de volta com payload completo

## Escala de Bloqueio (uso no integrador)

| Classificacao | Acao |
|---------------|------|
| Marca A (>aluguel)    | Nenhuma                                       |
| Marca B (50-100%)     | `bloqueio_recebimento=1` (Zoop, leve)         |
| Marca C (<50%)        | `principal=0` (Zoop, repasse total)           |
| Atraso grave          | `Fornecedores[bloqueio_vendas]=1`             |
| Inadimplencia critica | `Fornecedores[bloqueio_acesso]=1`             |

## Granularidade

- `cadastro_zoop.id` != `fornecedores.id` (tabelas e IDs diferentes).
- Juncao entre as duas: por `nome_fantasia` ou `CNPJ/CPF`.
- Uma marca pode ter VARIAS linhas em `cadastro_zoop` (PJ/PF, enabled/denied),
  mas geralmente 1 linha em `fornecedores`.

