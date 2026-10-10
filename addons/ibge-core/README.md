# ibge-core

Dados básicos do IBGE por UF e para o Brasil. Licença dos dados: CC-BY-4.0 (IBGE).

| Propriedade | Fonte | Período |
|---|---|---|
| `ibge-core/estado/populacao` | Censo Demográfico 2022 — população residente | 2022 |
| `ibge-core/estado/area_km2` | Áreas territoriais 2022 | 2022 |
| `ibge-core/pais/populacao` | Censo Demográfico 2022 — população residente | 2022 |

## Procedência dos números

Os valores de população são os resultados do Censo 2022 (população residente por UF, total
203.080.756) e as áreas são as áreas territoriais oficiais de 2022, digitados a partir de
tabelas públicas do IBGE. Antes da Fase 3 (builder `.bmd`) eles devem ser conferidos contra a
API do IBGE:

- População: SIDRA, tabela 4714 (`https://apisidra.ibge.gov.br/values/t/4714/n3/all/v/93/p/2022`).
- Áreas: `https://servicodados.ibge.gov.br/api/v3/malhas/...` ou a planilha "Áreas territoriais"
  em `https://www.ibge.gov.br/geociencias/organizacao-do-territorio/estrutura-territorial/15761-areas-dos-municipios.html`.

A soma das 27 UFs em `estado_populacao.csv` deve bater com `pais_populacao.csv`; o teste
`tests/test_ibge_core.py` confere isso.
