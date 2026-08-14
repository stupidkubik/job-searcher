# HelloWorld.rs search playbook

Checked: 2026-08-14

Current references:

- [IT jobs and internships](https://www.helloworld.rs/oglasi-za-posao/)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
HelloWorld.rs-specific правила.

## Роль и доступ

HelloWorld.rs — локальный Serbia-focused discovery board. Использовать
`source=HelloWorld.rs`; exact card сохранять как provenance, а canonical status
проверять на employer careers/ATS, если такой route существует.

Board сравнительно небольшой, поэтому предпочтителен последовательный полный
проход, а не сложная эвристика ранней остановки.

## Routes: narrow → broad

| Pass | Query/categories | Назначение |
|---|---|---|
| Narrow | Frontend, React, JavaScript, Web Developer | основной web signal |
| Broad | Software, Game Developer, Creative/Web, UI | adjacent и нестандартные titles |
| Geo/work mode | Serbia, remote, hybrid и подходящие города | проверить локальный/remote scope |

Сначала пройти весь narrow result set, затем весь broad result set. Game
Developer не исключать: tracked TRIA card дала сильный playable-ads match через
Canvas/WebGL/Phaser/Three.js.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | `/posao/.../<numeric-id>` |
| stable `source_job_id` | numeric suffix; pattern подтверждён на трёх tracked URLs |
| `source_url` | exact HTTPS card; нормализовать `www`/non-`www` и tracking |
| original route | external Apply/employer link → exact BambooHR, Ashby или другая employer surface |

Numeric suffix использовать целиком; title/company path может меняться. Generic
company profile и search page не являются exact source URL.

## Source status и first-party boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| live exact card | HelloWorld.rs listing доступна | external requisition open |
| expired/removed card | source-side closure | отсутствие repost у работодателя |
| external Apply | candidate route найден | exact route всё ещё принимает заявки |
| local remote/hybrid label | board work-mode classification | global eligibility |

Observed outcomes подтверждают все ветки: Zoftify разрешился в живой BambooHR,
Stedi — в живой Ashby, а сильный по стеку TRIA card был уже закрыт.

## Trust и ловушки

- Technology, seniority и work-mode labels полезны для ranking, но hard blocker
  сверяется с полным employer text/form.
- `Rad od kuće`/Remote не означает найм из любой страны.
- Local company spelling может отличаться от employer/ATS name.
- Старый exact card нужно записать даже при закрытии, чтобы не переоткрывать его
  в следующем полном проходе.

## Stop rule

Источник обработан после полного narrow scan и полного broad scan текущей board,
включая дубли между queries. Каждая открытая numeric card получает outcome по
универсальному lifecycle.
