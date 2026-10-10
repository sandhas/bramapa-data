# bramapa-data

Addons de dados do **Bramapa**, o atlas isométrico 2.5D do Brasil em pixel art. Aqui ficam os
pacotes declarativos (sem código) que o motor usa pra pintar o mapa: séries temporais por entidade
(país, estado, município ou tipos novos que um addon declare), com fonte, licença e regra de
exibição no próprio pacote.

Os quatro repositórios: `bramapa` (motor Rust+wgpu e as specs), `bramapa-tileset` (atlas de
tiles), `bramapa-pipeline` (gera os chunks do mapa a partir de dados geográficos) e este
`bramapa-data` (addons + validador + builder `.bmd`). Este repo só produz dados; quem desenha é
o motor.

Contrato: [`docs/spec/addon.md`](https://github.com/bramapa/bramapa/blob/main/docs/spec/addon.md)
no repositório `bramapa`. Estamos em `spec_version = 0`, que é instável e pode quebrar sem aviso
até o MVP existir.

## Estrutura

```
addons/
  ibge-core/              # população, PIB e área por UF e pro Brasil (API SIDRA do IBGE)
  _template/              # copie para começar um addon novo; "_" = ignorado pelo validador
src/bramapa_data/         # validador, builder .bmd e CLI
tools/fetch_ibge.py       # regenera os CSVs do ibge-core a partir do SIDRA
tests/                    # pytest, com fixtures de addons quebrados em tests/fixtures/
```

## Setup

Precisa de Python 3.12+ e [uv](https://docs.astral.sh/uv/).

```sh
uv sync                              # cria .venv e instala o pacote + pytest
uv run bramapa-data validate         # valida tudo em addons/ (sai com código 1 se houver ERROR)
uv run bramapa-data list             # lista addons e ids canônicos das propriedades
uv run bramapa-data build --out build/   # valida e gera os .bmd + index.toml pro motor
uv run bramapa-data inspect build/ibge-core/estado/populacao.bmd   # olha dentro de um .bmd
uv run pytest                        # testes
```

`validate` aceita outro diretório como argumento (`uv run bramapa-data validate caminho/addons`)
— ou vários (`uv run bramapa-data validate addons ../bramapa-addon-energia/addons`), validados
como um conjunto só: ids únicos entre todos, `depends` resolvido entre eles. Imprime uma linha
por achado no formato `ERROR <addon>: <mensagem>` ou `WARN <addon>: ...`. Só `ERROR` derruba o
build; `WARN` é pra você olhar. Addons mantidos em outros repositórios estão listados em
[COMMUNITY.md](COMMUNITY.md).

O que o validador checa está em `addon.md` (as 8 regras): `spec_version`, id do addon, ids
duplicados, `entity_type` resolvível, arquivos existentes e CSV no formato certo, chave
`(entity, period_start, period_end)` única, `render`/`map_overrides` apontando pra algo real e
`depends` sem ciclo.

## Build (`.bmd`)

O motor não lê CSV. `bramapa-data build [ADDONS_DIR ...] --out DIR` valida tudo (qualquer `ERROR`
aborta sem escrever nada; vários diretórios de addons entram numa saída só) e transforma cada propriedade em um **`.bmd`**: um arquivo colunar
pequeno — cabeçalho de 24 bytes (magic `BMDT`, `spec_version`, `dtype`, contagens) seguido de uma
carga zstd com a tabela de entidades e as colunas `entity_idx`, `period_start`, `period_end` (dias
desde 1970-01-01, inclusivo) e `value`, ordenadas por entidade e data pra permitir busca binária.
O formato está em [`docs/spec/data-binary.md`](https://github.com/bramapa/bramapa/blob/main/docs/spec/data-binary.md).

```
DIR/
  index.toml                          # o motor começa por aqui
  ibge-core/manifest.toml             # cópia do manifesto do addon
  ibge-core/estado/populacao.bmd
  ibge-core/estado/pib.bmd
  ibge-core/estado/area_km2.bmd
  ibge-core/pais/populacao.bmd
  ibge-core/pais/pib.bmd
```

`index.toml` lista os addons (id, versão, caminho do manifesto) e as propriedades (id canônico,
arquivo, número de linhas, `period_min`/`period_max` em ISO e em dias, mais `name`, `unit`,
`dtype`, `entity_type`, `periodicity`, `addon`). O build é determinístico: a mesma entrada produz
exatamente os mesmos bytes (zstd nível 3, tamanho do conteúdo gravado no frame, sem checksum),
então dá pra versionar ou cachear a saída com segurança. `bramapa-data inspect ARQUIVO.bmd`
imprime o cabeçalho e as primeiras linhas com datas legíveis.

## Addons disponíveis

| Addon | Propriedades | Licença dos dados |
|---|---|---|
| `ibge-core` | `estado/populacao`, `estado/pib`, `estado/area_km2`, `pais/populacao`, `pais/pib` | CC-BY-4.0 |

### Procedência dos dados do `ibge-core`

Tudo vem da API pública do SIDRA (`apisidra.ibge.gov.br`), sem chave, via `tools/fetch_ibge.py`
(`uv run python tools/fetch_ibge.py` reescreve os CSVs; os CSVs ficam versionados porque são
pequenos). Tabelas:

| Tabela SIDRA | Variável | Vira |
|---|---|---|
| [6579](https://sidra.ibge.gov.br/tabela/6579) Estimativas da população | 9324 | `populacao` 2001–2026 (anual; sem 2007, 2010, 2022, 2023) |
| [4714](https://sidra.ibge.gov.br/tabela/4714) Censo 2022 | 93 | `populacao` em 2022 (prevalece sobre a estimativa) |
| [4714](https://sidra.ibge.gov.br/tabela/4714) Censo 2022 | 6318 | `area_km2` (km², 2022) |
| [5938](https://sidra.ibge.gov.br/tabela/5938) PIB dos municípios/UFs | 37 | `pib` a preços correntes, R$ mil, 2002–2023 |

Detalhes e ressalvas (anos faltantes, arredondamentos) em
[`addons/ibge-core/README.md`](addons/ibge-core/README.md).

Quer adicionar um? Veja o [CONTRIBUTING.md](CONTRIBUTING.md).

## O que vem depois

- **Municípios**: `municipio/populacao`, `municipio/pib` e `municipio/area_km2` pros 5.570
  municípios (as mesmas tabelas SIDRA com `n6/all`).
- **Censos anteriores**: preencher 2007 (Contagem) e 2010 (Censo) em `populacao`.
- **Mais tabelas**: o `fetch_ibge.py` já tem a mecânica; falta escolher as próximas séries.

## Licenças

O código deste repositório (validador, CLI, testes) é licenciado sob MIT **ou** Apache-2.0, à sua
escolha — veja [LICENSE-MIT](LICENSE-MIT) e [LICENSE-APACHE](LICENSE-APACHE).

**Os dados de cada addon têm licença própria**, declarada em `addon.license` no `manifest.toml`
(e opcionalmente por propriedade em `properties[].license`). Os dados do `ibge-core` são do IBGE,
distribuídos sob CC-BY-4.0.
