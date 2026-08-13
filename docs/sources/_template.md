# <Source> search playbook

Checked: YYYY-MM-DD

Official references:

- <official API or product documentation>
- <official URL/board documentation>

Общий lifecycle, provenance semantics и write paths описаны в
[`README.md`](README.md). Здесь фиксируются только особенности `<Source>`.

## Роль в поиске

- Что этот source даёт discovery-процессу.
- Является ли он first-party ATS или агрегатором.
- Где допустим широкий поиск и где начинается проверка кандидата.

## Как распознать source

- URL patterns.
- Как получить board/company identifier.
- Как распознать custom careers integration.
- Что нельзя угадывать при неполных данных.

## Discovery

- Narrow query families.
- Broad/experimental query families.
- Geography discovery.
- Когда открывать всю board и искать adjacent roles.

## Официальный интерфейс

- Публичные endpoints или страницы.
- Нужна ли авторизация.
- Пагинация, rate limits и freshness caveats.
- Как получить board, список jobs, exact job и application fields.

## Идентификаторы и URL

| Значение | Правило |
|---|---|
| board/company identifier | ... |
| stable job identifier | ... |
| canonical first-party URL | ... |
| tracking query parameters | ... |

Если `source=Company Careers` объединяет несколько ATS, namespace-ить
`source_job_id`, например `<ats>:<board>:<job-id>`, чтобы избежать межплатформенных
коллизий.

## Проверка listing и Apply

Определить независимые доказательства для:

- `listing_status=open`;
- `listing_status=closed`;
- `first_party_verified=yes`;
- `apply_verified=yes`.

Указать, какие сигналы являются только предварительными и не должны записываться
как подтверждённые facts.

## Проверка geography и hard blockers

- Где искать location/remote restrictions.
- Какие поля формы могут раскрывать work authorization или residency blocker.
- Типичные неоднозначности конкретного source.

## Нормализация

| Source field | Tracker/inbox use |
|---|---|
| ... | ... |

Не выдумывать отсутствующие даты, salary, location или eligibility facts.

## Типичные ловушки

- ...

## Checklist результата

- [ ] preflight и dedupe выполнены;
- [ ] exact first-party job проверена;
- [ ] Apply проверен отдельно;
- [ ] geography и hard blockers прочитаны полностью;
- [ ] source provenance сохранён без подмены ATS-хостом;
- [ ] результат записан разрешённым write path;
- [ ] canonical dataset и generated tracker проверены.

