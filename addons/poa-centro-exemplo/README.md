# poa-centro-exemplo

Primeiro override manual de mapa do Bramapa. Substitui o chunk `[6, 11]` do nível 3 de Porto
Alegre (centro histórico, lon −51,2300 / lat −30,0330) por uma praça desenhada: parque central
com árvores, avenidas em cruz, anel de prédios e casas ao redor. A camada de entidade do chunk
original é preservada, então hover e clique continuam funcionando.

Para regenerar a partir de um nível 3 construído pelo pipeline:

```sh
uv run --group tools python tools/make_override.py \
  --level ../bramapa-levels/3/municipio_4314902 --lon -51.2300 --lat -30.0330 \
  --out addons/poa-centro-exemplo/map/centro
```

O motor aplica o override ao carregar o nível (precedência por `priority`).
