# Addons da comunidade

Addons do Bramapa mantidos **fora** deste repositório, cada um no seu próprio git. Pra entrar na
lista, abra um PR adicionando uma linha; a revisão só confere que o addon valida limpo junto com
os daqui (`uv run bramapa-data validate addons <caminho-do-seu>/addons`) e que a licença dos
dados está declarada. Como fazer um addon assim está no
[CONTRIBUTING.md](CONTRIBUTING.md#addon-no-seu-próprio-repositório).

| Addon (`addon.id`) | Nome | Repositório | Licença dos dados | Propriedades |
|---|---|---|---|---|
| `energia` | Energia elétrica — tarifas e capacidade instalada | [sandhas/bramapa-addon-energia](https://github.com/sandhas/bramapa-addon-energia) | ODbL-1.0 (ANEEL) | `estado/tarifa_residencial`, `pais/tarifa_residencial`, `estado/capacidade_instalada`, `pais/capacidade_instalada` |

Pra usar um addon da lista, clone o repositório ao lado deste e passe os dois diretórios pro
build (`uv run bramapa-data build addons ../bramapa-addon-energia/addons --out ../bramapa-data-build`).
Ids de addon são únicos no ecossistema inteiro, inclusive entre os daqui e os daí: o validador
recusa dois `addon.id` iguais em diretórios diferentes.
