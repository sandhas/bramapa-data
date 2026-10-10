# bramapa-data

Addons de dados do **Bramapa**, o atlas isométrico 2.5D do Brasil em pixel art. Aqui ficam os
pacotes declarativos (sem código) que o motor usa pra pintar o mapa: séries temporais por entidade
(país, estado, município ou tipos novos que um addon declare), com fonte, licença e regra de
exibição no próprio pacote.

Os quatro repositórios: `bramapa` (motor Rust+wgpu e as specs), `bramapa-tileset` (atlas de
tiles), `bramapa-pipeline` (gera os chunks do mapa a partir de dados geográficos) e este
`bramapa-data` (addons + validador + futuro builder). Este repo só produz dados; quem desenha é
o motor.

Contrato: [`docs/spec/addon.md`](https://github.com/bramapa/bramapa/blob/main/docs/spec/addon.md)
no repositório `bramapa`. Estamos em `spec_version = 0`, que é instável e pode quebrar sem aviso
até o MVP existir.

## Estrutura

```
addons/
  ibge-core/              # população e área por UF, população do Brasil (Censo 2022)
  _template/              # copie para começar um addon novo; "_" = ignorado pelo validador
src/bramapa_data/         # validador + CLI
tests/                    # pytest, com fixtures de addons quebrados em tests/fixtures/
```

## Setup

Precisa de Python 3.12+ e [uv](https://docs.astral.sh/uv/).

```sh
uv sync                              # cria .venv e instala o pacote + pytest
uv run bramapa-data validate         # valida tudo em addons/ (sai com código 1 se houver ERROR)
uv run bramapa-data list             # lista addons e ids canônicos das propriedades
uv run pytest                        # testes
```

`validate` aceita outro diretório como argumento (`uv run bramapa-data validate caminho/addons`)
e imprime uma linha por achado no formato `ERROR <addon>: <mensagem>` ou `WARN <addon>: ...`.
Só `ERROR` derruba o build; `WARN` é pra você olhar.

O que o validador checa está em `addon.md` (as 8 regras): `spec_version`, id do addon, ids
duplicados, `entity_type` resolvível, arquivos existentes e CSV no formato certo, chave
`(entity, period_start, period_end)` única, `render`/`map_overrides` apontando pra algo real e
`depends` sem ciclo.

## Addons disponíveis

| Addon | Propriedades | Licença dos dados |
|---|---|---|
| `ibge-core` | `estado/populacao`, `estado/area_km2`, `pais/populacao` | CC-BY-4.0 |

Quer adicionar um? Veja o [CONTRIBUTING.md](CONTRIBUTING.md).

## O que vem depois

- **Fase 3 — builder**: `bramapa-data build` transforma cada propriedade em um `.bmd` colunar
  comprimido (formato em `docs/spec/data-binary.md`) mais um `index.toml`, prontos pro motor
  carregar sem parsear CSV.
- **Municípios**: `municipio/populacao` e `municipio/area_km2` pros 5.570 municípios.
- **Séries anuais via API SIDRA**: script que puxa estimativas anuais de população e outras
  tabelas direto do IBGE, em vez de valores digitados à mão.

## Licenças

O código deste repositório (validador, CLI, testes) é licenciado sob MIT **ou** Apache-2.0, à sua
escolha — veja [LICENSE-MIT](LICENSE-MIT) e [LICENSE-APACHE](LICENSE-APACHE).

**Os dados de cada addon têm licença própria**, declarada em `addon.license` no `manifest.toml`
(e opcionalmente por propriedade em `properties[].license`). Os dados do `ibge-core` são do IBGE,
distribuídos sob CC-BY-4.0.
