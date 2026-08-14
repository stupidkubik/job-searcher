# Startit Jobs search playbook

Checked: 2026-08-14

Current references:

- [Startit poslovi](https://startit.rs/poslovi/)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
Startit Jobs-specific правила.

## Роль и доступ

Startit Jobs — небольшой Serbian discovery board. Использовать
`source=Startit Jobs`. В tracker history пока нет подтверждённой exact vacancy с
этого источника, поэтому identity и archive semantics нельзя выводить задним
числом.

## Routes: narrow → broad

| Pass | Query/categories | Назначение |
|---|---|---|
| Narrow | Frontend, React, JavaScript, Web Developer | основной web signal |
| Broad | Software, Product, UI, Game/Creative/Web | adjacent titles |
| Geo/work mode | location, remote и level filters, если они видимы | screening leads |

Board небольшой: пройти narrow полностью, затем broad полностью. Нулевой
результат — допустимый outcome прохода; не создавать фиктивные вакансии ради
coverage.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | отдельная vacancy page, подтверждённая через UI |
| stable `source_job_id` | оставить unset до наблюдения и offline validation нескольких URLs |
| `source_url` | exact vacancy URL без tracking; форму заранее не угадывать |
| original route | employer/Apply link → exact employer/ATS listing |

Нельзя выводить ID из slug, query parameter или DOM position по одному примеру.
Когда появятся несколько tracked cards, отдельно проверить URL persistence,
repost behavior и collisions перед изменением этого контракта.

## Source status и first-party boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| card видна на current board | source listing доступна | employer requisition open |
| card исчезла из board | source-side removal | canonical closure |
| Apply/employer link | candidate route | first-party ownership или live form |
| source location/remote label | discovery geo | Serbia/global eligibility |

Archive/stale mapping остаётся `unknown` до реального observed case; любое
решение о canonical status принимает employer surface.

## Trust и ловушки

- Не переизобретать stable ID и archive semantics без evidence.
- Маленькая board не отменяет narrow → broad: adjacent title может быть
  единственным подходящим результатом.
- Generic company page или контакт не является exact employer vacancy.
- Отсутствие canonical additions в прошлом проходе не означает, что источник
  бесполезен или всегда пуст.

## Stop rule

Остановиться только после полного narrow и полного broad scan текущей board.
Если открыта exact card, она обязана получить outcome; если exact cards не
открывались, зафиксировать coverage в отчёте запуска, не создавая job rows.
