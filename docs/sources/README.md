# Source search playbooks

Эта директория содержит инструкции по поиску и проверке вакансий в конкретных
ATS и job sources. Они образуют единый search layer поверх существующего
tracker workflow, но не создают новый источник истины и не заменяют правила
репозитория.

## Границы ответственности

| Слой | Где задан |
|---|---|
| профиль, допустимая география, уровень и подтверждённый опыт | [`config/profile.md`](../../config/profile.md) |
| общие семейства поисковых запросов | [`config/search-queries.md`](../../config/search-queries.md) |
| машинная политика включённых adapters | [`config/sources.toml`](../../config/sources.toml) |
| особенности конкретной ATS или площадки | `docs/sources/<source>.md` |
| raw batch contract | [`data/inbox/README.md`](../../data/inbox/README.md) |
| canonical поля и enum | [`data/schema.md`](../../data/schema.md) |
| разрешённые write paths | [`AGENTS.md`](../../AGENTS.md) и [`data/operations/README.md`](../../data/operations/README.md) |

Playbook отвечает на вопросы «как найти board», «как получить опубликованные
вакансии», «какой идентификатор стабилен» и «как проверить listing и Apply».
Он не должен копировать профиль кандидата, схему CSV, синтаксис write-команд или
придумывать новые lifecycle-состояния.

## Доступные playbooks

| Source | Роль в search layer |
|---|---|
| [Greenhouse](greenhouse.md) | first-party ATS discovery и verification через публичный Job Board API |
| [Hirify](hirify.md) | агрегатор и AI discovery; [детерминированные настройки](hirify-discovery-rules.md), [technical discovery](hirify-technical-discovery.md) и обязательный переход к работодателю/ATS |
| [LinkedIn](linkedin.md) | широкий signed-in discovery; exact numeric job ID и осторожная работа с Easy Apply |
| [Himalayas](himalayas.md) | remote discovery через публичный API и локальный fetch-only adapter |
| [Wellfound](wellfound.md) | startup discovery и нативная application surface |
| [Welcome to the Jungle](welcome-to-the-jungle.md) | discovery по Европе и нативные/внешние Apply-маршруты |
| [We Work Remotely](we-work-remotely.md) | remote board с exact cards и внешними Apply-маршрутами |
| [HiringCafe](hiringcafe.md) | широкий агрегатор с детальными фильтрами; verification только у работодателя/ATS |

## ATS не равна discovery source

Greenhouse, Lever или Ashby могут быть техническим хостом первоисточника, но это
не означает, что они должны стать значением `source`.

- Если вакансия найдена через HiringCafe, Hirify или другую площадку, сохранить
  эту площадку в `source`/`source_url`, а проверенную ATS-карточку — в
  `original_url`.
- Если вакансия найдена прямым поиском по ATS или текущей careers board,
  использовать `source=Company Careers`; конкретную карточку можно сохранить и
  как `source_url`, и после проверки как `original_url`.
- Не создавать вторую canonical job только потому, что та же вакансия появилась
  в другом discovery source. Добавить provenance reference через разрешённый
  write path.

## Обязательный workflow

### 1. Preflight

Перед любым поиском:

1. прочитать `data/jobs.csv` целиком;
2. прочитать `config/profile.md`;
3. открыть playbook нужной ATS;
4. проверить существующие references в `data/job_sources.csv`.

Строки со статусами `applied` или `rejected` не анализировать и не обрабатывать
повторно. Для остальных существующих строк продолжить с сохранённого
`next_action` и текущего состояния.

### 2. Discovery

Использовать несколько широких query families, а не один чрезмерно точный
запрос. Найденную интересную карточку считать входом не только в exact job, но и
в текущую board компании: подходящая соседняя роль может называться иначе.

Широкий discovery не отменяет запись результатов. Каждая конкретная вакансия,
которую агент открыл и оценил, должна получить canonical запись или source
reference, даже если она закрыта, является дублем или содержит hard blocker.

### 3. Dedupe до анализа

Проверять в таком порядке:

1. `source + source_job_id` в `data/job_sources.csv`;
2. нормализованный exact first-party URL в `original_url`;
3. discovery URL в source references;
4. нормализованные `company + role` и fuzzy-кандидаты.

Совпадение не разрешает молча объединять строки. Использовать только
предусмотренный `--duplicate-of` или эквивалентный immutable connector request.

### 4. First-party verification

Для новой exact job:

1. подтвердить, что board принадлежит работодателю;
2. проверить наличие exact job в текущей публичной board/API;
3. открыть полное описание;
4. открыть видимую кандидату Apply-страницу или форму;
5. проверить geography, work authorization, office requirements, seniority и
   обязательные screening questions;
6. записать дату проверки.

Ответ API, поисковый сниппет, `Remote` в заголовке или future expiry date сами по
себе не доказывают ни применимость географии, ни работоспособность Apply.

### 5. Outcome

- Закрытая exact job: записать `listing_status=closed` и
  `decision_reason=closed_before_application`, затем проверить текущую board на
  соседние релевантные роли.
- Открытая job с hard blocker: записать структурированную причину через `add` или
  `screen`, без полного анализа и application card.
- Неясный blocker или необычная, но потенциально подходящая роль: оставить
  `reviewing` с конкретным `next_action`.
- Прошедшая фильтр job: провести полный анализ, выставить `match_score`, создать
  `applications/<id>.md` и принять решение `apply` или вычисляемый `Skipped`.

Агент не отправляет заявку и не ставит `application_status=applied`; это возможно
только после явного подтверждения человека.

### 6. Write path и проверка

Локальный агент пишет только через `scripts/jobs.py`. GitHub connector создаёт
только immutable request по контракту `data/operations/README.md` и ждёт
canonical result от trusted runner. Прямое редактирование `data/jobs.csv` и
`data/job_sources.csv` запрещено.

После canonical write обязательны strict validation, fuzzy duplicate review и
проверка generated tracker согласно `AGENTS.md`.

## Добавление нового playbook

Скопировать [`_template.md`](_template.md), оставить только source-specific
поведение и подтвердить технические утверждения официальной документацией.
Если появляется adapter, отдельно зарегистрировать его машинную политику в
`config/sources.toml`; наличие Markdown playbook само по себе source не включает.
