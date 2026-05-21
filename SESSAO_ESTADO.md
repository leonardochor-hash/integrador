# Estado da sessao - 21/05/2026

Documento de retomada do projeto **integrador**. Resume o que foi feito ate aqui
e os proximos passos para continuar em outra sessao sem perder contexto.

## Objetivo geral

Integrador Python que conecta LivePDV + Efi + Asaas + Airtable + Zoho + Gmail
para identificar marcas inadimplentes e executar acoes automatizadas.

Regras de classificacao (vendas dos ultimos 30 dias vs aluguel mensal):

- **A**: vendas_30d >= aluguel (saudavel)
- **B**: 50% <= vendas_30d / aluguel < 100% (alerta)
- **C**: 0  <  vendas_30d / aluguel < 50% (critico)
- **D**: vendas_30d == 0 (silencio)
- **?**: dados incompletos / aluguel ausente

## Estado dos modulos

| Modulo | Status | Observacoes |
|---|---|---|
| efi_client.py | OK | URLs atualizadas para cobrancas.api.efipay.com.br + /v1/authorize |
| livepdv_client.py | OK | Lista expositores (1267) - sem endpoint de vendas_30d ainda |
| excel_inadimplentes.py | OK | Le .xls (xlrd==1.2.0) e .xlsx (openpyxl) - filtro Status=Inadimplente |
| classificador.py | OK | Implementacao completa A/B/C/D + ratio |
| relatorio_inadimplentes.py | OK | Suporta --excel, --real, --csv, --cnpj, --dias |
| asaas_client.py | PENDENTE | Nao iniciado |
| gmail_notifier.py | PENDENTE | Nao iniciado |
| runner.py | PENDENTE | Nao iniciado |
| README.md | DESATUALIZADO | Falta documentar fluxo Excel |

## Descobertas tecnicas importantes

1. **A API /v1/charges da Efi so devolve cobrancas emitidas via API**, nao
   cobrancas criadas manualmente pelo painel "Receber". Foi testado:
   - Todos os 5 IDs de boletos inadimplentes retornam 500 "property_does_not_exists"
   - Filtros por todos os anos 2020-2026, billet+carnet, devolvem qtd=0
   - Conta confirmada correta, escopos habilitados, sem subconta
2. **Solucao adotada**: exportar planilha .xls do painel Efi
   (Receber > Gestao de cobrancas > Boletos > Exportar) e carregar via
   excel_inadimplentes.py.
3. **GitHub raw cacheia agressivamente**. Usar a API
   api.github.com/repos/.../contents/...?ref=main com header
   "Accept: application/vnd.github.raw" para sempre obter a versao fresca.
4. **classificador.py estava truncado no repo** (apenas docstring inicial,
   235 bytes). Foi reescrito do zero com a logica completa.

## Ultimo teste bem-sucedido (21/05/2026 18:13)

```
python relatorio_inadimplentes.py --real --excel arquivo.xls --csv

[1/4] Conectando ao LivePDV... OK (1267 expositores)
[2/4] Lendo planilha Excel... OK (10 CNPJs inadimplentes)
[3/4] Cruzando CNPJs LivePDV x Efi... OK
[4/4] Montando relatorio... OK (10 marcas no relatorio)

RESUMO
  Total inadimplentes:   10 marcas
  Valor total em aberto: R$ 15.851,51
  Maior atraso:          28 dias (CNPJ 20439036000183)

Exportado para: ./relatorios/inadimplentes_real_2026-05-21_1813.csv
```

F.A.V.VIANA (Status=Cancelado) foi corretamente excluida.
Coluna "Classe" aparece como "?" porque LivePDV ainda nao expoe vendas_30d.

## Como retomar a sessao

### Setup rapido no Colab

```bash
%%bash
for f in excel_inadimplentes.py relatorio_inadimplentes.py classificador.py efi_client.py livepdv_client.py; do
  curl -sH 'Accept: application/vnd.github.raw' \
    "https://api.github.com/repos/leonardochor-hash/integrador/contents/$f?ref=main" -o $f
done
pip install -q openpyxl xlrd==1.2.0
```

### Variaveis de ambiente necessarias

- LIVEPDV_TOKEN
- EFI_CLIENT_ID, EFI_CLIENT_SECRET, EFI_CERT_PATH

### Upload da planilha

```python
from google.colab import files
up = files.upload()
arq = list(up.keys())[0]
```

### Rodar relatorio

```bash
!python relatorio_inadimplentes.py --real --excel "$arq" --csv
```

## Proximos passos (em ordem de prioridade)

1. **Investigar endpoint de vendas no LivePDV** para destravar a
   classificacao A/B/C/D. Sem isso, todas as marcas ficam como "?".
2. Criar **asaas_client.py** se houver boletos no Asaas tambem.
3. Criar **gmail_notifier.py** para enviar alertas para marcas C/D.
4. Criar **runner.py** orquestrando o fluxo end-to-end.
5. Atualizar **README.md** documentando o fluxo Excel como metodo principal
   enquanto boletos forem emitidos manualmente no painel Efi.

## Decisoes em aberto

- Como obter o valor de aluguel por marca? (Airtable? LivePDV custom field?)
- Frequencia do runner? (cron diario? semanal?)
- Quem recebe os alertas Gmail? (financeiro? gerente da loja?)
