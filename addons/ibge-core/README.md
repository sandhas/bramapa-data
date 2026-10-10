# ibge-core

Dados básicos do IBGE por UF e para o Brasil, puxados da API pública do SIDRA. Licença dos
dados: CC-BY-4.0 (IBGE).

| Propriedade | Fonte (tabela SIDRA) | Período | Linhas |
|---|---|---|---|
| `ibge-core/estado/populacao` | 6579 v/9324 (estimativas) + 4714 v/93 (Censo 2022) | 2001–2026, anual | 621 |
| `ibge-core/estado/pib` | 5938 v/37 — PIB a preços correntes (R$ mil) | 2002–2023, anual | 594 |
| `ibge-core/estado/area_km2` | 4714 v/6318 — área territorial (km²) | 2022, pontual | 27 |
| `ibge-core/pais/populacao` | 6579 v/9324 + 4714 v/93 | 2001–2026, anual | 23 |
| `ibge-core/pais/pib` | 5938 v/37 | 2002–2023, anual | 22 |

## Procedência

Todos os CSVs em `data/` são **gerados** por `tools/fetch_ibge.py` (na raiz do repo), que chama
`https://apisidra.ibge.gov.br/values/t/<tabela>/n3/all/v/<variável>/p/all` (UFs) e `n1/all`
(Brasil), sem chave. Não edite os CSVs à mão: rode o script de novo.

```sh
uv run python tools/fetch_ibge.py            # reescreve addons/ibge-core/data/*.csv
uv run python tools/fetch_ibge.py --dry-run  # só mostra o que viria
```

- **População** (`populacao`): a tabela 6579 (Estimativas da população residente) não tem os
  anos de Censo/Contagem nem 2023 — hoje faltam **2007, 2010, 2022 e 2023**. O ano de 2022 é
  preenchido com a população residente do **Censo Demográfico 2022** (tabela 4714, variável 93).
  Se o IBGE um dia publicar estimativa para 2022, o valor do Censo continua valendo (regra do
  script). 2007 e 2010 seguem em branco; a Contagem 2007 e o Censo 2010 são candidatos pra uma
  próxima versão. A soma das 27 UFs bate exatamente com o Brasil em todos os anos.
- **PIB** (`pib`): tabela 5938 (Contas Regionais), variável 37 "Produto Interno Bruto a preços
  correntes", unidade "Mil Reais" → `unit = "R$ mil"`, `dtype = "i64"` (o SIDRA publica inteiros).
  Valores **nominais**, não deflacionados. A soma das UFs difere do Brasil por poucas unidades
  (arredondamento de cada UF para R$ mil).
- **Área** (`area_km2`): tabela 4714, variável 6318 "Área da unidade territorial", 2022. São os
  valores oficiais (até a Fase 3 havia 8 UFs com diferenças de metros quadrados em relação a
  números digitados de memória; agora vêm direto da API). A soma das UFs é 8 510 417,774 km²
  contra 8 510 417,771 km² publicados para o Brasil — arredondamento.

Páginas das tabelas: [6579](https://sidra.ibge.gov.br/tabela/6579),
[4714](https://sidra.ibge.gov.br/tabela/4714), [5938](https://sidra.ibge.gov.br/tabela/5938).

Os testes em `tests/test_ibge_core.py` conferem 27 UFs em todo ano, soma UF = Brasil para
população, soma UF ≈ Brasil para PIB e a área total.
