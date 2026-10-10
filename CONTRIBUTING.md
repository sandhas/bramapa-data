# Contribuindo com um addon

Um addon é só um diretório com `manifest.toml` e CSVs. Sem código. Se você tem uma tabela pública
por estado ou município e sabe de onde ela veio, você consegue fazer um addon.

## Passo a passo

1. **Copie o template**: `cp -r addons/_template addons/<seu-addon-id>`. O id segue `[a-z0-9-]+`
   e tem que ser igual ao nome do diretório. Escolha algo que identifique a fonte, tipo
   `aneel-usinas` ou `inep-escolas`; não precisa ser curto, precisa ser único.
2. **Preencha o `manifest.toml`**: nome, versão (semver), licença dos dados, uma propriedade por
   coluna que você quer expor. Cada propriedade aponta pra um CSV com cabeçalho exatamente
   `entity,period_start,period_end,value`. Ids de entidade são `pais:BR`, `estado:43`,
   `municipio:4314902` (códigos IBGE) ou `<tipo>:<codigo>` pra tipos que seu addon declara.
   Períodos em ISO 8601 (`2022`, `2022-03` ou `2022-03-15`); `period_end` vazio vale igual ao
   `period_start`.
3. **Escreva um `README.md`** no addon dizendo de onde vieram os números (link pra publicação
   original) e o que você transformou, se transformou.
4. **Rode `uv run bramapa-data validate`** até sair `OK`. Cada `ERROR` traz o arquivo e a linha.
5. **Rode `uv run bramapa-data build --out /tmp/bmd`** pra ver seu addon virar `.bmd` e aparecer
   no `index.toml`; `uv run bramapa-data inspect /tmp/bmd/<addon>/<tipo>/<prop>.bmd` mostra as
   primeiras linhas como o motor vai ler. Não comite a saída do build.
6. **Abra um PR** com o diretório novo. A revisão olha procedência dos dados e licença, não
   estilo; o validador já cuidou do formato.

Pra atualizar um addon existente, mude a `version` no manifesto (patch pra corrigir número,
minor pra adicionar propriedade ou período, major se mudou id ou removeu algo).

Se seus dados vêm de uma API (como o `ibge-core`, que puxa do SIDRA via `tools/fetch_ibge.py`),
comite o script junto e gere os CSVs com ele em vez de digitar: fica reprodutível e a revisão
consegue rodar o mesmo comando.

## "Nunca se sobrepõe"

Todo id de propriedade é prefixado pelo id do addon (`ibge-core/estado/populacao`), então dois
addons medindo a mesma coisa — digamos, população por UF segundo o IBGE e segundo uma estimativa
do TCU — coexistem lado a lado sem que um sobrescreva o outro, e é o usuário do atlas quem escolhe
qual exibir. Por isso não existe um addon "oficial" de população nem uma fila pra ocupar um nome:
você publica a sua leitura dos dados com o seu prefixo e pronto.

## Licença dos dados

O `manifest.toml` declara em `addon.license` a licença **dos dados**, não do seu trabalho de
empacotar. Use o identificador SPDX da licença que o órgão de origem publica: dados do IBGE são
CC-BY-4.0, dados do Portal da Transparência costumam ser ODbL ou CC-BY, dados.gov.br varia por
conjunto. Se uma propriedade tem licença diferente das demais, declare em `properties[].license`.
Não publique dados cuja licença você não consegue apontar; na dúvida, pergunte no PR antes de
digitar 5.570 linhas.

O código do repositório (validador, CLI) é MIT ou Apache-2.0; contribuições de código entram sob
as duas.
