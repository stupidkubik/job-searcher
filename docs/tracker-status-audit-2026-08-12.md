# Аудит статусов tracker

> Historical record. Not a contract.

Дата среза: 2026-08-12
Dataset: 131 вакансия, `data/jobs.csv` после commit `690ee8c`

## Короткий вывод

Таблица стала сложнее не потому, что данные потерялись, а потому, что v2 хранит
три разных измерения отдельно:

1. `application_status` — что происходит с нашим решением или заявкой;
2. `listing_status` — доказано ли, что объявление открыто или закрыто;
3. `decision_reason` — почему мы не продолжаем кейс.

Это хорошая модель для целостности данных, но плохой интерфейс для быстрого
чтения строки. В сыром CSV нет главного человекочитаемого столбца
`case_status`, поэтому техническое `listing_status=unknown` визуально
перетягивает внимание и выглядит как неопределённость всего кейса.

`unknown` не означает «непонятно, что делать с вакансией». Оно означает только
«нет структурированного подтверждения open/closed из первоисточника».

## Что сейчас находится в таблице

### Application lifecycle

| `application_status` | Количество |
|---|---:|
| `not_started` | 108 |
| `applied` | 17 |
| `reviewing` | 4 |
| `apply` | 2 |
| остальные статусы | 0 |

### Listing status

| `listing_status` | Количество | Доля |
|---|---:|---:|
| `unknown` | 100 | 76.3% |
| `closed` | 25 | 19.1% |
| `open` | 6 | 4.6% |

### Реальное состояние кейсов

Если использовать уже существующую функцию `derived_state`, картина намного
понятнее:

| Человекочитаемое состояние | Количество |
|---|---:|
| Skipped | 75 |
| Closed | 25 |
| Applied | 17 |
| Not started | 7 |
| Reviewing | 4 |
| Apply | 2 |
| Duplicate | 1 |

То есть у 118 из 131 строки уже есть однозначный основной исход.
Работа сосредоточена не во всей таблице, а в 13 активных pre-application
кейсах: семь `not_started`, четыре `reviewing` и два `apply`.

## Являются ли `listing_status=unknown` бывшими Skipped

Частично, но не все.

Из 100 строк с `listing_status=unknown`:

| Текущее вычисляемое состояние | Количество |
|---|---:|
| Skipped | 72 |
| Applied | 17 |
| Not started | 7 |
| Reviewing | 2 |
| Apply | 1 |
| Duplicate | 1 |

История миграции уточняет происхождение этих строк:

- 48 — действительно прежние v1 `Skipped`, мигрированные в
  `not_started + decision_reason + listing_status=unknown`;
- 24 — новые screening-решения после миграции, в основном Himalayas. Их
  намеренно отсеяли по discovery-данным без утверждения, что первоисточник был
  проверен;
- 28 — вообще не Skipped: 17 `Applied`, 7 `Not started`, 2 `Reviewing`, 1
  `Apply` и 1 legacy `Duplicate`.

Следовательно, массово заменять `unknown` на `closed` или `open` нельзя: это
создаст факты, которых в данных нет.

## Где именно возникает путаница

### 1. Сырой CSV одновременно является storage и интерфейсом

Первые колонки `application_status` и `listing_status` технически корректны, но
для чтения конкретного кейса человеку приходится мысленно вычислять:

```text
application_status + listing_status + decision_reason + stage_reached
```

Например, `not_started / unknown / geo_restriction` на самом деле означает
однозначное `Skipped: geo_restriction`, а не незавершённый кейс.

### 2. Слово `unknown` слишком сильное для значения «не проверяли»

У всех 100 строк с неизвестным listing status одновременно стоят
`first_party_verified=unknown` и `apply_verified=unknown`. В интерфейсе это
лучше показывать как `Not checked`, а не как три отдельных `unknown`.

### 3. Проверка listing нужна не всем строкам одинаково

Проверять первоисточник у 72 уже отсеянных вакансий обычно невыгодно. Их решение
известно и не зависит от актуальности объявления. Аналогично 17 отправленных
заявок не становятся непонятными только потому, что объявление после отправки
не перепроверялось.

Реально важная очередь неизвестной актуальности сейчас состоит из десяти
активных pre-application строк с `listing_status=unknown`:

```text
job-0022, job-0023, job-0054, job-0065, job-0066,
job-0067, job-0068, job-0069, job-0128, job-0129
```

Ещё три активные pre-application записи — `job-0124`, `job-0127` и
`job-0130` — уже имеют подтверждённый `open`.

### 4. Историческая verification-разметка неполная

Только семь строк имеют `first_party_verified=yes`. У 24 закрытых строк
verification остаётся `unknown`: закрытие было зафиксировано до появления
строгих verification-полей или без достаточного структурированного
доказательства. Это технический долг, но не причина менять их основной статус
`Closed`.

## Рекомендуемая человекочитаемая таблица

Canonical CSV следует оставить нормализованным. Поверх него нужен вычисляемый
default view с такими первыми колонками:

| Колонка view | Источник |
|---|---|
| `id` | canonical `id` |
| `case_status` | существующий `derived_state(row)` |
| `company` | canonical |
| `role` | canonical |
| `stage` | `stage_reached`, только после отправки |
| `next_action` | canonical |
| `next_action_date` | canonical |
| `match_score` | canonical |
| `listing_check` | вычисляемое `Open / Closed / Not checked` |
| `last_update` | canonical |

Пример представления:

| ID | Case status | Company | Role | Next action | Listing check |
|---|---|---|---|---|---|
| job-0099 | Skipped: geo restriction | Homeward | Software Engineer, Front-end | — | Not checked |
| job-0022 | Reviewing | Canonical | Web Frontend Engineer | prepare application | Not checked |
| job-0088 | Applied | defdone | Frontend Developer | follow-up | Not checked |
| job-0102 | Closed | REW Technology | Front End Engineer | — | Closed, verified |

В таком виде `listing_status` остаётся доступен как независимый факт, но больше
не притворяется главным статусом строки.

## Рекомендуемые рабочие views

Вместо одной таблицы «всё сразу» полезны четыре очереди:

1. **Action now** — `reviewing`, `apply`, интервью и просроченные next actions.
2. **Applications** — `applied`, `interviewing`, `offer`, `rejected`, `ghosted`,
   `withdrawn`; сортировка по последнему событию.
3. **To verify** — только активные pre-application записи без подтверждённого
   первоисточника; сейчас это десять строк.
4. **Archive** — `Skipped`, `Closed`, `Duplicate`; listing verification здесь
   вторична.

## Рекомендуемый порядок изменений

1. Не менять значения 100 `unknown` массовым backfill.
2. Сделать `case_status` главным полем всех human-facing отчётов и будущей
   compact-table команды.
3. В отображении переименовать `unknown` в `Not checked`; schema enum можно не
   менять.
4. Провести first-party verification только для десяти активных unknown-кейсов.
5. Перепроверять listing у applied-записей по событию: follow-up, ответ или
   ручная ревизия, а не ради заполнения столбца.
6. Следующим отдельным изменением добавить read-only команду вроде
   `jobs.py list --view active|applications|verify|archive`, не расширяя
   canonical CSV новым вычисляемым столбцом.

Главная рекомендация: сохранить строгую v2-модель как storage, но перестать
показывать сырой storage как основной пользовательский интерфейс.
