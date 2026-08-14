# <Source> search playbook

Checked: YYYY-MM-DD

Current references:

- <official or current source page>

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь нет его
копии — только отличия `<Source>`.

## Роль и доступ

- aggregator, job board или first-party ATS;
- нужна ли авторизация и какие действия остаются read-only;
- tracker `source` value и особая provenance semantics, если она есть.

## Routes: narrow → broad

| Pass | Route/filters | Назначение |
|---|---|---|
| Narrow | ... | ... |
| Broad | ... | ... |
| Adjacent | ... | ... |

Указать пагинацию/recency depth и особенности сортировки. Общие query families
не копировать из `config/search-queries.md`.

## Exact identity и original source

| Значение | Source-specific правило |
|---|---|
| exact card | ... |
| stable `source_job_id` | ... |
| normalized `source_url` | ... |
| original source route | ... |

Указать, какие URL/ID нельзя использовать и как распознаются repost/location
variants.

## Source status и first-party boundary

| Source signal | Что он доказывает | Чего он не доказывает |
|---|---|---|
| ... | ... | ... |

Описать archive/stale/removed behavior и источник окончательного canonical
status. Не повторять общий verification workflow.

## Trust и ловушки

- какие поля достаточно надёжны для discovery;
- какие labels, AI summaries, geo/remote/visa/salary fields требуют проверки;
- source-specific redirects, paywalls, personalization и identity traps.

## Stop rule

Источник обработан, когда <source-specific coverage condition>. Общий stop rule
из [`README.md`](README.md) остаётся обязательным.
