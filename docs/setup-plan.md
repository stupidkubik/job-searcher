# План развертывания `job-searcher`

Дата: 2026-08-09
Статус: план готов к исполнению; preflight-решения внесены в профиль, реорганизация ещё не начиналась.

Документ рассчитан на то, что основным исполнителем работы по вакансиям будет ИИ-агент, а человек принимает решения. Поэтому приоритет — не богатство схемы, а **однозначность правил**: агент не должен угадывать, куда писать и какие значения допустимы.

---

## 0. Что показал анализ текущего состояния

Факты, а не предположения — всё проверено в репозитории.

### 0.1. Три несовместимые модели данных одновременно

| Где | Модель |
|---|---|
| `README.md` | `data/jobs.csv`, поля `original_url`, `source_url`, `remote_policy`, `match_score`, `decision_reason`, `cv_version`; 11 статусов |
| `02-applications.csv` (реальный файл) | корень, а не `data/`; поля `job_url`, `work_format`, `fit_score`, `resume_version`, `why_fit`, `risks_or_gaps`, `next_action`; статус `Researching` |
| `04-weekly-review.md` | воронка `Researching → Ready to apply → Applied → Recruiter screen → Interview → Test task → Offer` |

Ни один статус из `04-weekly-review.md` не входит в список статусов README. Это главная проблема: агент, читающий README, и агент, заполняющий weekly review, будут писать разные значения в одно поле.

### 0.2. ID нестабильны по конструкции

README предлагает `normalized-company|normalized-role` (`exequt|front-end-software-developer`), реальный CSV использует `001`. Схема из README ломается при любой правке названия роли — а роль в агрегаторе и в оригинальном ATS почти всегда написана по-разному. Ссылки из `applications/`, weekly-review и коммитов при этом становятся мёртвыми.

### 0.3. Один статус `Rejected` уничтожает аналитику

`Rejected` после автоотказа на этапе скрининга и `Rejected` после финального интервью — это два принципиально разных исхода, и именно их различие отвечает на вопрос «что у меня ломается: попадание в воронку или прохождение по ней». Нужны два поля: текущее состояние и максимально достигнутая стадия.

### 0.4. `cv/` — 24 PDF без системы

- дубликаты: `Evgenii Rubin CV.pdf`, `... copy.pdf`, `... copy 2.pdf`, `Rubin Evgenii CV.pdf`, `Rubin_Evgenii.pdf`, `Rubin_Evgenii_CV.pdf`, `evgenii-rubin-cv.pdf`;
- company-specific: `... CV Percona.pdf`, `... CV WG.pdf`, `... CV CRM manager.pdf`;
- 5 cover letters лежат вместе с резюме;
- русские версии (`Рубин Евгений CV.pdf`, `Рубин Евгений HTML-верстальщик.pdf` и др.);
- актуальное `evgenii-rubin-cv-08-2026.pdf` лежит **не** в `cv/`, а в корне;
- **`cv/MargaritaSavonevskayaCV.pdf` — резюме другого человека.** Персональные данные третьего лица в вашем Git-репозитории. Требует отдельного решения (шаг 3).
- `Evgenii-Rubin-1769505962835-Psychometric.pdf` — результаты психометрии, тоже чувствительный документ.

При этом `01-profile-context.md` уже ссылается на `cv/Evgenii Rubin UX Engineer.pdf` — то есть путь придётся обновить при любой реорганизации.

### 0.5. Гигиена репозитория

- `.gitignore` отсутствует;
- `.DS_Store` и `cv/.DS_Store` **закоммичены** (видно в `git log --stat`);
- remote настроен: `https://github.com/stupidkubik/job-searcher.git`, ветка `main`, 3 коммита;
- через GitHub подтверждено: репозиторий private, у текущего подключения есть admin/push-доступ;
- `gh` CLI не установлен (нужен только для v2-интеграций, не блокер);
- локально доступны Python 3.14.6 и Node 24.18 → скрипты можно писать на Python **без зависимостей**.

### 0.6. Позиционирование зафиксировано

Основное направление — Frontend; Creative Developer и UI Engineer остаются дополнительными вариантами. Целевой уровень — Junior / Junior+, потому что прямой коммерческий опыт продуктовой frontend-разработки ограничен. Graduate и Associate допустимы, Junior/Middle рассматривается только как stretch. Эти решения уже внесены в `01-profile-context.md`, который переезжает в `config/profile.md` и становится единственным источником истины.

---

## 1. Принятые решения по архитектуре

Обосновываю коротко, потому что каждое из них закрывает конкретную проблему из раздела 0.

| Решение | Почему |
|---|---|
| **CSV + Markdown**, не SQLite | На текущей стадии главная ценность — читаемые диффы в Git и то, что ИИ-агент может править файл напрямую без слоя доступа. SQLite оправдан при появлении UI или нескольких writers. |
| `data/jobs.csv` — **единственный** структурированный источник | Убирает `02-applications.csv` из корня и приводит реальность к README |
| ID вида `job-0001`, **immutable** | Название компании и роли можно исправлять, не ломая ссылки |
| Два поля: `status` + `stage_reached` | Решает 0.3 |
| Длинный текст (`why_fit`, риски, JD, вопросы формы) → `applications/<id>.md` | CSV остаётся аналитическим и не ломается от переводов строк в ячейках |
| Значения в CSV — **только английский**, документация — русский | Агент не должен выбирать между `Applied` и `Отправлено` |
| Скрипты — Python 3, **stdlib only** | Ноль установки, работает в CI из коробки |
| `AGENTS.md` в корне — канонический операционный контракт | Codex читает его автоматически; `CLAUDE.md` остаётся коротким указателем для Claude Code |

Главный принцип, который я сохраняю из вашего README: **ни одна найденная вакансия не исчезает без записи**. Всё остальное подчинено ему.

---

## 2. Целевая структура

```text
job-searcher/
├── README.md                       # короткий: что это, как пользоваться, ссылки
├── AGENTS.md                       # канонические операционные правила для ИИ-агента
├── CLAUDE.md                       # указатель на AGENTS.md для Claude Code
├── .gitignore
├── config/
│   ├── profile.md                  # ← из 01-profile-context.md, единственный источник о кандидате
│   └── search-queries.md           # готовые запросы под каждый источник
├── data/
│   ├── jobs.csv                    # ЕДИНСТВЕННЫЙ структурированный источник истины
│   └── schema.md                   # словарь полей + допустимые значения (enum)
├── applications/
│   ├── _TEMPLATE.md
│   └── job-0001-exequt-frontend.md
├── cv/
│   ├── current/                    # то, что реально отправляется
│   ├── archive/                    # всё остальное, read-only
│   └── cover-letters/
├── templates/
│   ├── outreach.md                 # ← из 03-outreach-templates.md
│   └── weekly-review.md            # ← из 04-weekly-review.md
├── reports/
│   ├── weekly/                     # 2026-W32.md
│   └── audits/                     # linkedin-2026-08-02.md
├── scripts/
│   └── jobs.py                     # add / validate / dupes / set / report
├── tests/
│   └── test_jobs.py                # stdlib unittest для write-path и инвариантов
├── docs/
│   ├── setup-plan.md               # этот файл
│   ├── architecture.md             # решения и их обоснование
│   └── roadmap.md
└── .github/
    └── workflows/
        └── validate.yml
```

Что куда уезжает из текущего состояния:

| Сейчас | Станет |
|---|---|
| `01-profile-context.md` | `config/profile.md` |
| `02-applications.csv` | `data/jobs.csv` (новая схема; единственная строка — пустой placeholder, переносить нечего) |
| `03-outreach-templates.md` | `templates/outreach.md` |
| `04-weekly-review.md` | `templates/weekly-review.md` |
| `linkedin-audit-2026-08-02.md` | `reports/audits/linkedin-2026-08-02.md` |
| `README.md` (1080 строк) | разделяется: правила → `AGENTS.md`, схема → `data/schema.md`, обоснования → `docs/architecture.md`, автоматизация → `docs/roadmap.md`; в README остаётся ~120 строк навигации |
| `evgenii-rubin-cv-08-2026.pdf` (корень) | `cv/current/cv-frontend-2026-08.pdf` |
| `deep-research-report.md` | `docs/architecture.md` (как основа) |

README не удаляется — он разбирается на части. Это важно: в нём много содержательного (dedup-иерархия, workflow из 8 шагов, decision reasons), и всё это переезжает в `AGENTS.md`, где будет реально применяться агентом.

---

## 3. Схема `data/jobs.csv`

27 колонок. Порядок фиксирован — `validate` проверяет его буквально, чтобы агент не мог перепутать колонки при ручной вставке строки.

```csv
id,status,company,role,level,original_url,source_url,source,location,remote_policy,stack,salary,posted_at,found_at,match_score,stage_reached,decision_reason,applied_at,response_at,next_action,next_action_date,cv_version,cover_letter,contact_name,contact_url,last_update,notes
```

### Обязательные при создании записи

`id`, `company`, `role`, `source`, `found_at`, `status`, `stage_reached`, `last_update`

Всё остальное может быть пустым — это осознанно: вакансия со `status=Skipped, decision_reason=geo_restriction` должна добавляться за 20 секунд, без анализа.

### Поля

| Поле | Тип / значения | Заметки |
|---|---|---|
| `id` | `job-NNNN` | immutable, выдаётся `jobs.py add` |
| `company` | текст | как в оригинальном источнике |
| `role` | текст | как в оригинальном источнике |
| `level` | `Intern` \| `Graduate` \| `Junior` \| `Junior+` \| `Associate` \| `Junior/Middle` \| `Middle` \| `Senior` \| `Unknown` | |
| `original_url` | URL | ATS/careers-страница. Основной ключ dedupe |
| `source_url` | URL | где нашли (агрегатор) |
| `source` | `Hirify` \| `Jaabz` \| `LinkedIn` \| `Company Careers` \| `Referral` \| `Manual` \| `Other` | для аналитики по площадкам |
| `location` | текст | как написано у работодателя |
| `remote_policy` | `Global` \| `Europe` \| `EMEA` \| `Serbia` \| `Country-specific` \| `Hybrid` \| `On-site` \| `Unclear` | «Remote» ≠ `Global`, всегда проверять текст |
| `stack` | `React; Next.js; TypeScript` | разделитель `; `, не запятая (CSV) |
| `salary` | текст \| `Unknown` | |
| `posted_at` | `YYYY-MM-DD` | |
| `found_at` | `YYYY-MM-DD` | |
| `match_score` | `1`–`10`, допускается `7.5` | субъективно, не автоматическое решение |
| `status` | см. ниже | текущее состояние |
| `stage_reached` | см. ниже | максимально достигнутая стадия |
| `decision_reason` | enum, см. ниже | обязателен для `Skipped` / `Closed` / `Duplicate` / `Withdrawn` |
| `applied_at` | `YYYY-MM-DD` | ставится **только** после фактической отправки; обязателен от `Applied` и для `Withdrawn` |
| `response_at` | `YYYY-MM-DD` | дата первого ответа компании; обязателен для `Interviewing` / `Offer` / `Rejected` |
| `next_action` | короткий текст | `follow-up`, `prepare test task`, `answer recruiter` |
| `next_action_date` | `YYYY-MM-DD` | по нему строится «что делать сегодня» |
| `cv_version` | slug | `frontend-2026-08`, соответствует файлу в `cv/current/` |
| `cover_letter` | `no` \| путь | `cv/cover-letters/job-0001-exequt.md` |
| `contact_name` | текст | рекрутёр / сотрудник |
| `contact_url` | URL | LinkedIn-профиль |
| `last_update` | `YYYY-MM-DD` | обновляется при каждом изменении строки |
| `notes` | одна строка | **без переводов строк**; длинный текст → `applications/<id>.md` |

### `status` — текущее состояние (12 значений)

```text
New          вакансия найдена, не анализировалась
Reviewing    идёт проверка первоисточника и требований
Apply        решено откликнуться, ещё не отправлено
Applied      заявка отправлена
Interviewing процесс идёт: скрининг / интервью / тестовое
Offer        получен оффер
Rejected     получен отказ
Ghosted      ответа нет >30 дней после отклика (или после последнего контакта)
Skipped      рассмотрено, решено не откликаться
Closed       вакансия закрылась до отправки заявки
Duplicate    копия уже существующей записи (в notes указать id оригинала)
Withdrawn    заявка отозвана мной
```

`Ghosted` — добавлен относительно README: без него все «молчащие» отклики годами висят в `Applied` и завышают активную воронку.

### `stage_reached` — максимальная достигнутая стадия (7 значений, упорядочены)

```text
None → Applied → Recruiter screen → Tech interview → Test task → Final interview → Offer
```

Правило: значение **только растёт**, никогда не уменьшается. `validate` это проверяет.

Ровно это даёт ответ на вопрос «где я теряюсь»:

```text
status = Rejected, stage_reached = Applied          → проблема в CV / ATS-фильтре
status = Rejected, stage_reached = Final interview  → проблема в интервью, CV работает
```

Стадии из `04-weekly-review.md` сохранены почти дословно, кроме `Researching` и `Ready to apply` — они являются состояниями (`Reviewing`, `Apply`), а не достигнутыми стадиями воронки, поэтому переехали в `status`.

### `decision_reason` (enum)

```text
geo_restriction         work_authorization      seniority_too_high
seniority_too_low       stack_mismatch          role_not_frontend
salary_too_low          company_not_interesting closed_before_application
already_applied         duplicate_listing       no_response_timeout
withdrawn_by_me         other
```

При `other` пояснение обязательно в `notes`.

---

## 4. Пошаговое исполнение

Каждый шаг заканчивается проверкой. Команды рассчитаны на запуск из `/Users/evgenii/Desktop/JOB`.

---

### Шаг 1. Подстраховка

```bash
cd /Users/evgenii/Desktop/JOB

# не перезаписываем уже существующий бэкап
test ! -e ../JOB-backup-2026-08-09

# полная копия рядом с проектом, вне git, включая незакоммиченные решения в плане
cp -pR . ../JOB-backup-2026-08-09

# проверяем, что Git-история копии читается
git -C ../JOB-backup-2026-08-09 fsck --no-dangling

# работаем в ветке, main остаётся нетронутым
git switch -c codex/restructure
```

Проверено 2026-08-09 через GitHub: репозиторий `stupidkubik/job-searcher` — private, у текущего подключения есть admin/push-доступ. Перед пушем всё равно не добавлять новые чувствительные документы без осознанного решения.

**Проверка шага:** `git branch --show-current` выводит `codex/restructure`, а `git status --short` показывает только два заранее известных изменения: `docs/setup-plan.md` и `01-profile-context.md`.

---

### Шаг 2. Гигиена: `.gitignore` и `.DS_Store`

Создать `.gitignore`:

```gitignore
# macOS
.DS_Store
._*
.Spotlight-V100
.Trashes

# редакторы
.vscode/
.idea/
*.swp

# Python
__pycache__/
*.pyc
.venv/

# черновики и приватное, что не должно уезжать даже в приватный репо
*.local.md
.claude/settings.local.json
scratch/
tmp/
```

Убрать уже закоммиченные файлы из индекса:

```bash
git rm --cached .DS_Store cv/.DS_Store
find . -name .DS_Store -not -path './.git/*' -delete
```

**Проверка:** `git status --short` не показывает `.DS_Store`.

Сразу зафиксировать этап, пока последующие `git mv` ещё не добавлены в индекс:

```bash
git add .gitignore
git commit -m "chore: add gitignore and drop DS_Store"
```

---

### Шаг 3. Персональные данные — решение зафиксировано

Выбрано осознанно: `cv/MargaritaSavonevskayaCV.pdf` остаётся в приватном репозитории и на шаге 6 переезжает в `cv/archive/`. Это **не** удаляет персональные данные третьего лица из Git-истории и не уменьшает круг доступа при появлении новых collaborators; решение нужно пересмотреть, если приватность или состав участников репозитория изменятся.

`Evgenii-Rubin-1769505962835-Psychometric.pdf` также переезжает в `cv/archive/`. Содержимое обоих PDF не требуется открывать для реорганизации.

Force-push и переписывание истории в этом плане не выполняются.

---

### Шаг 4. Скелет директорий

```bash
mkdir -p config data applications cv/current cv/archive cv/cover-letters \
         templates reports/weekly reports/audits scripts tests docs .github/workflows
```

Пустые директории Git не хранит. Создать `reports/weekly/README.md`:

```markdown
# Weekly reports

Автоматические и ручные отчёты `YYYY-Www.md`, созданные командой
`python3 scripts/jobs.py report`.
```

---

### Шаг 5. Перемещение файлов (`git mv` — сохраняет историю)

```bash
git mv 01-profile-context.md        config/profile.md
git mv 03-outreach-templates.md     templates/outreach.md
git mv 04-weekly-review.md          templates/weekly-review.md
git mv linkedin-audit-2026-08-02.md reports/audits/linkedin-2026-08-02.md
git mv deep-research-report.md      docs/architecture.md   # затем дописать руками
```

`02-applications.csv` **не** переносится: его единственная строка — пустой placeholder (`001,,,,,...,Researching,...`), переносить нечего.

```bash
git rm 02-applications.csv
```

После перемещения обязательно поправить устаревший путь в `config/profile.md`:
`evgenii-rubin-cv-08-2026.pdf` → `cv/current/cv-frontend-2026-08.pdf`.
UX Engineer version не является актуальной и уже удалена из таблицы активных материалов; на шаге 6 она уходит в архив.

Создать `config/search-queries.md` как исполнимую матрицу поиска:

```markdown
# Поисковые запросы

Единственный источник приоритетов — `profile.md`. Перед изменением запросов сначала
обновить профиль.

## Основные — Frontend Junior / Junior+

- `junior frontend developer React TypeScript remote Europe`
- `junior frontend engineer React Serbia`
- `graduate frontend engineer React`
- `associate frontend developer TypeScript`
- `junior React developer remote EMEA`
- `junior Next.js developer remote`

## Stretch

- `frontend developer React TypeScript 2 years remote Europe`
- `software engineer frontend React junior remote`
- `fullstack React Next.js Node.js junior remote`

## Дополнительные варианты

- `junior UI engineer design systems React`
- `creative developer HTML CSS JavaScript remote`

Для каждого источника сохранять ссылку выдачи как `source_url`, но актуальность и
ограничения проверять только в `original_url` работодателя/ATS.
```

Сразу закоммитить структурные перемещения. На этом этапе в индексе находятся
только выполненные выше `git mv` / `git rm` и новые структурные файлы:

```bash
git add config templates reports docs/architecture.md
git commit -m "refactor: move tracker files into target structure"
```

---

### Шаг 6. Разбор `cv/`

Файлы с пробелами и кириллицей в именах — плохо для скриптов и ссылок. Приводим `cv/current/` к slug-схеме `cv-<фокус>-<YYYY-MM>.pdf`; архив переименовывать не обязательно.

```bash
git mv evgenii-rubin-cv-08-2026.pdf cv/current/cv-frontend-2026-08.pdf

cd cv

# cover letters — отдельно от резюме
git mv Ciklum_Cover_Letter_Evgenii_Rubin.pdf                       cover-letters/
git mv GetBlock_Cover_Letter_Evgenii_Rubin.pdf                     cover-letters/
git mv GoDaddy_User_Experience_Engineer_Cover_Letter_Evgenii_Rubin.pdf cover-letters/
git mv TripleTen_CRM_Cover_Letter_Evgenii_Rubin.pdf                cover-letters/
git mv Horizon_Trading_Solutions_Junior_Frontend_Application_Evgenii_Rubin.pdf cover-letters/

# всё остальное в архив
for f in *.pdf; do git mv "$f" archive/; done
cd ..
```

Порядок важен: `for`-цикл идёт последним и подбирает всё, что осталось в корне `cv/`, включая файлы с кириллицей и `copy`/`copy 2`.

`cv/current/` в итоге содержит ровно 1 PDF — то, что реально отправляется. `Evgenii Rubin UX Engineer.pdf` подберёт архивный `for`-цикл. Правило: **если резюме не в `current/`, оно не используется для откликов.**

Создать `cv/current/README.md`:

```markdown
# Актуальные версии резюме

| Файл | Для каких ролей | `cv_version` в jobs.csv | Обновлено |
|---|---|---|---|
| `cv-frontend-2026-08.pdf` | Frontend / Software Engineer | `frontend-2026-08` | 2026-08-05 |

Правила:
- в `cv_version` пишется slug из третьей колонки, не имя файла;
- новая версия = новый файл с новой датой, старая уходит в `../archive/`;
- файлы из `../archive/` для откликов не используются.
```

Значения `cv_version` в CSV должны совпадать с третьей колонкой этой таблицы — иначе аналитика «какая версия CV даёт больше ответов» не соберётся.

Сразу зафиксировать весь CV-блок:

```bash
git add -A cv
git commit -m "chore(cv): split into current archive and cover letters"
```

---

### Шаг 7. `data/jobs.csv` и `data/schema.md`

`data/jobs.csv` — только заголовок:

```csv
id,status,company,role,level,original_url,source_url,source,location,remote_policy,stack,salary,posted_at,found_at,match_score,stage_reached,decision_reason,applied_at,response_at,next_action,next_action_date,cv_version,cover_letter,contact_name,contact_url,last_update,notes
```

`data/schema.md` — раздел 3 этого документа, перенесённый как есть. Это тот файл, который агент читает перед записью, поэтому он должен быть отдельным и коротким, без обоснований и истории решений.

---

### Шаг 8. `applications/_TEMPLATE.md`

Здесь живёт всё, что не влезает в CSV: JD, ответы на вопросы формы, переписка. Одна вакансия = один файл, имя `job-NNNN-<company-slug>-<role-slug>.md`.

```markdown
---
id: job-0000
company:
role:
original_url:
---

# {{company}} — {{role}}

## Проверка первоисточника

- [ ] вакансия открыта
- [ ] Apply работает, нет «No longer accepting applications»
- [ ] локация и remote-ограничения проверены в тексте
- [ ] seniority
- [ ] work authorization
- Дата проверки:

## Требования (выжимка)

## Почему подхожу

| Требование вакансии | Моё доказательство | Метрика |
|---|---|---|
|  |  |  |

## Риски и пробелы

## Что отправлено

- CV version:
- Cover letter:
- Ответы на вопросы формы:
- Salary expectations:

## Хронология

| Дата | Событие |
|---|---|
|  |  |
```

Таблица «требование → доказательство → метрика» намеренно повторяет структуру раздела «Доказательства для откликов» из `config/profile.md` — агент заполняет её, копируя оттуда, а не выдумывая.
Статус намеренно не дублируется во front matter: он живёт только в `data/jobs.csv` и меняется через `jobs.py set`.

---

### Шаг 9. `scripts/jobs.py`

Один файл, только stdlib, работает на Python 3.9+. Пять команд:

| Команда | Что делает |
|---|---|
| `add` | выдаёт следующий `id`, проверяет дубли, дописывает строку, создаёт файл в `applications/` |
| `validate` | проверяет текущую схему, enum, даты, уникальность и межполевые инварианты; код возврата 1 при ошибке → годится для CI |
| `dupes` | fuzzy-поиск дублей по `company` + `role` |
| `set` | меняет разрешённые поля, запрещает правку `id`/`stage_reached`/`last_update`, не даёт понижать стадию |
| `report` | воронка, эффективность источников, конверсия по `match_score`, просроченные `next_action` |

```python
#!/usr/bin/env python3
"""jobs.py — CLI для data/jobs.csv. Только стандартная библиотека."""

import argparse
import csv
import math
import os
import re
import sys
import tempfile
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "jobs.csv"
APPS_DIR = ROOT / "applications"
TEMPLATE_PATH = APPS_DIR / "_TEMPLATE.md"

FIELDS = [
    "id", "company", "role", "level", "original_url", "source_url", "source",
    "location", "remote_policy", "stack", "salary", "posted_at", "found_at",
    "match_score", "status", "stage_reached", "decision_reason", "applied_at",
    "response_at", "next_action", "next_action_date", "cv_version",
    "cover_letter", "contact_name", "contact_url", "last_update", "notes",
]

REQUIRED = ["id", "company", "role", "source", "found_at", "status",
            "stage_reached", "last_update"]
DATE_FIELDS = ["posted_at", "found_at", "applied_at", "response_at",
               "next_action_date", "last_update"]

STATUSES = ["New", "Reviewing", "Apply", "Applied", "Interviewing", "Offer",
            "Rejected", "Ghosted", "Skipped", "Closed", "Duplicate", "Withdrawn"]

STAGES = ["None", "Applied", "Recruiter screen", "Tech interview", "Test task",
          "Final interview", "Offer"]

LEVELS = ["Intern", "Graduate", "Junior", "Junior+", "Associate",
          "Junior/Middle", "Middle", "Senior", "Unknown"]

REMOTE = ["Global", "Europe", "EMEA", "Serbia", "Country-specific", "Hybrid",
          "On-site", "Unclear"]

SOURCES = ["Hirify", "Jaabz", "LinkedIn", "Company Careers", "Referral",
           "Manual", "Other"]

REASONS = ["geo_restriction", "work_authorization", "seniority_too_high",
           "seniority_too_low", "stack_mismatch", "role_not_frontend",
           "salary_too_low", "company_not_interesting",
           "closed_before_application", "already_applied", "duplicate_listing",
           "no_response_timeout", "withdrawn_by_me", "other"]

# статусы, требующие непустой decision_reason
NEEDS_REASON = {"Skipped", "Closed", "Duplicate", "Withdrawn"}
# статусы, требующие непустой applied_at
NEEDS_APPLIED_AT = {"Applied", "Interviewing", "Offer", "Rejected", "Ghosted",
                    "Withdrawn"}
RESPONDED_STATUSES = {"Interviewing", "Offer", "Rejected"}
ADD_STATUSES = ["New", "Reviewing", "Apply", "Skipped", "Closed"]
SET_PROTECTED = {"id", "stage_reached", "last_update"}

GHOST_AFTER_DAYS = 30

ENUMS = {
    "status": STATUSES, "stage_reached": STAGES, "level": LEVELS,
    "remote_policy": REMOTE, "source": SOURCES, "decision_reason": REASONS,
}


# ---------- вспомогательное ----------

def today():
    return date.today().isoformat()


def load():
    if not CSV_PATH.exists():
        die(f"не найден {CSV_PATH}")
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            die("заголовок jobs.csv не совпадает со схемой; см. data/schema.md")
        return list(reader)


def save(rows):
    """Атомарно заменить CSV, не оставляя обрезанный файл при сбое."""
    fd, tmp_name = tempfile.mkstemp(prefix="jobs-", suffix=".csv",
                                    dir=CSV_PATH.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: (row.get(k) or "") for k in FIELDS})
        os.replace(tmp_name, CSV_PATH)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def norm(text):
    """ExeQut / EXEQUT / ExeQut Ltd. -> exequt ltd"""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = "".join(c if c.isalnum() else " " for c in text)
    return re.sub(r"\s+", " ", text).strip()


def norm_url(value):
    """Убрать fragment, trailing slash и известные tracking-параметры."""
    if not value:
        return ""
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return value.strip()
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")
             and k.lower() not in {"ref", "referrer", "source"}]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path,
                       urlencode(query), ""))


COMPANY_NOISE = {"ltd", "limited", "inc", "incorporated", "llc", "llp", "plc",
                 "gmbh", "ag", "bv", "nv", "ab", "oy", "oyj", "as", "sa", "sas",
                 "srl", "spa", "doo", "ooo", "corp", "corporation", "co",
                 "company", "group", "holding", "holdings", "the"}

ROLE_NOISE = {"developer", "engineer", "software", "web", "senior", "junior",
              "middle", "mid", "associate", "graduate", "intern", "internship",
              "remote", "m", "f", "d", "x", "the", "and"}


def norm_company(text):
    """ExeQut Ltd. / EXEQUT LLC -> exequt"""
    words = [w for w in norm(text).split() if w not in COMPANY_NOISE]
    return " ".join(words) or norm(text)


def norm_role(text):
    words = [w for w in norm(text).split() if w not in ROLE_NOISE]
    return " ".join(words) or norm(text)


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


def slug(text, limit=28):
    return norm(text).replace(" ", "-")[:limit].strip("-")


def next_id(rows):
    nums = [int(m.group(1)) for r in rows
            if (m := re.fullmatch(r"job-(\d{4,})", r["id"] or ""))]
    return f"job-{max(nums, default=0) + 1:04d}"


def find(rows, job_id):
    for row in rows:
        if row["id"] == job_id:
            return row
    die(f"запись {job_id} не найдена")


# ---------- add ----------

def cmd_add(args):
    rows = load()
    company, role = args.company.strip(), args.role.strip()

    hits = {}
    if args.original_url:
        for r in rows:
            if r["original_url"] and norm_url(r["original_url"]) == norm_url(args.original_url):
                hits[r["id"]] = (r, "совпадение canonical original_url")
    nc, nr = norm_company(company), norm_role(role)
    for r in rows:
        cs = similar(nc, norm_company(r["company"]))
        if cs < 0.85:
            continue
        rs = similar(nr, norm_role(r["role"]))
        if rs >= 0.75:
            hits.setdefault(r["id"], (r, f"похоже: company {cs:.2f}, role {rs:.2f}"))

    if args.duplicate_of:
        original = find(rows, args.duplicate_of)
        status = "Duplicate"
        decision_reason = "duplicate_listing"
        duplicate_note = f"duplicate of {original['id']}"
        notes = f"{duplicate_note}; {args.notes}" if args.notes else duplicate_note
    else:
        status = args.status
        decision_reason = args.decision_reason or ""
        notes = args.notes or ""

    if hits and not args.force and not args.duplicate_of:
        print("возможные дубли:")
        for r, why in hits.values():
            print(f"  {r['id']}  {r['company']} — {r['role']}  [{r['status']}]  ({why})")
        print("\nэто дубль -> повторите с --duplicate-of job-NNNN")
        print("это другая вакансия -> повторите с --force")
        sys.exit(2)

    job_id = next_id(rows)
    row = {k: "" for k in FIELDS}
    row.update({
        "id": job_id, "company": company, "role": role,
        "level": args.level, "original_url": args.original_url or "",
        "source_url": args.source_url or "", "source": args.source,
        "location": args.location or "", "remote_policy": args.remote_policy,
        "stack": args.stack or "", "salary": args.salary or "Unknown",
        "posted_at": args.posted_at or "", "found_at": args.found_at or today(),
        "match_score": args.match_score or "", "status": status,
        "stage_reached": "None", "decision_reason": decision_reason,
        "last_update": today(), "notes": notes.replace("\n", " "),
    })
    rows.append(row)
    app_path = APPS_DIR / f"{job_id}-{slug(company)}-{slug(role)}.md"
    create_file = not args.no_file and status not in {"Duplicate", "Skipped", "Closed"}
    if create_file and not TEMPLATE_PATH.exists():
        die(f"не найден шаблон {TEMPLATE_PATH}")

    ensure_valid(rows)
    save(rows)

    if create_file and not app_path.exists():
        body = (TEMPLATE_PATH.read_text(encoding="utf-8")
                .replace("job-0000", job_id)
                .replace("{{company}}", company)
                .replace("{{role}}", role)
                .replace("company:", f"company: {company}", 1)
                .replace("role:", f"role: {role}", 1)
                .replace("original_url:", f"original_url: {args.original_url or ''}", 1))
        app_path.write_text(body, encoding="utf-8")
        print(f"создан {app_path.relative_to(ROOT)}")

    print(f"{job_id}  {company} — {role}  [{status}]")


# ---------- set ----------

def cmd_set(args):
    if not args.field and not args.stage:
        die("нечего менять: укажите field=value и/или --stage")
    rows = load()
    row = find(rows, args.id)

    for pair in args.field:
        if "=" not in pair:
            die(f"ожидается field=value, получено: {pair}")
        key, value = pair.split("=", 1)
        if key not in FIELDS:
            die(f"неизвестное поле: {key}")
        if key in SET_PROTECTED:
            die(f"поле {key} управляется скриптом и не меняется через field=value")
        if key == "status" and value == "Duplicate" and row["status"] != "Duplicate":
            die("Duplicate создаётся только командой add --duplicate-of JOB_ID")
        if key in ENUMS and value and value not in ENUMS[key]:
            die(f"{key}: недопустимое значение {value!r}\nдопустимо: {', '.join(ENUMS[key])}")
        row[key] = value.replace("\n", " ")

    # stage_reached только растёт
    if args.stage:
        if args.stage not in STAGES:
            die(f"недопустимая стадия: {args.stage}")
        current = row["stage_reached"] or "None"
        if STAGES.index(args.stage) < STAGES.index(current):
            die(f"stage_reached нельзя понижать: {current} -> {args.stage}")
        row["stage_reached"] = args.stage

        stage_index = STAGES.index(args.stage)
        if (STAGES.index("Recruiter screen") <= stage_index
                <= STAGES.index("Final interview")
                and row["status"] == "Applied"):
            row["status"] = "Interviewing"
        if args.stage == "Offer" and row["status"] in {"Applied", "Interviewing"}:
            row["status"] = "Offer"

    # автоматика для Applied
    if row["status"] in NEEDS_APPLIED_AT and not row["applied_at"]:
        row["applied_at"] = today()
    if row["status"] in NEEDS_APPLIED_AT and (row["stage_reached"] or "None") == "None":
        row["stage_reached"] = "Applied"
    if row["status"] == "Offer":
        row["stage_reached"] = "Offer"
    if row["status"] in RESPONDED_STATUSES and not row["response_at"]:
        row["response_at"] = today()

    row["last_update"] = today()
    ensure_valid(rows)
    save(rows)
    print(f"{row['id']}  status={row['status']}  stage={row['stage_reached']}")


# ---------- validate ----------

def validate_rows(rows):
    errors, warnings = [], []

    def err(i, msg):
        errors.append(f"строка {i}: {msg}")

    seen_ids, urls, duplicate_refs = {}, {}, []

    for i, row in enumerate(rows, start=2):
        rid = row["id"] or "<пусто>"

        if None in row:
            err(i, f"{rid}: лишние CSV-колонки: {row[None]}")

        for field in REQUIRED:
            if not (row[field] or "").strip():
                err(i, f"{rid}: пустое обязательное поле {field}")

        if row["id"] and not re.fullmatch(r"job-\d{4,}", row["id"]):
            err(i, f"{rid}: id должен быть вида job-NNNN")
        if row["id"] in seen_ids:
            err(i, f"{rid}: дубль id (уже в строке {seen_ids[row['id']]})")
        seen_ids[row["id"]] = i

        for field, allowed in ENUMS.items():
            value = (row[field] or "").strip()
            if value and value not in allowed:
                err(i, f"{rid}: {field}={value!r} не входит в {allowed}")

        for field in DATE_FIELDS:
            value = (row[field] or "").strip()
            if not value:
                continue
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                err(i, f"{rid}: {field}={value!r} — ожидается YYYY-MM-DD")
            else:
                if field != "next_action_date" and parsed > date.today():
                    warnings.append(f"строка {i}: {rid}: {field}={value} в будущем — опечатка в годе?")

        score = (row["match_score"] or "").strip()
        if score:
            try:
                parsed_score = float(score)
                if not math.isfinite(parsed_score) or not 1 <= parsed_score <= 10:
                    err(i, f"{rid}: match_score вне диапазона 1–10")
            except ValueError:
                err(i, f"{rid}: match_score не число: {score!r}")

        url = (row["original_url"] or "").strip()
        if url:
            try:
                parts = urlsplit(url)
                if parts.scheme not in {"http", "https"} or not parts.netloc:
                    raise ValueError
                canonical_url = norm_url(url)
            except ValueError:
                err(i, f"{rid}: original_url не является http(s) URL: {url!r}")
            else:
                urls.setdefault(canonical_url, []).append((i, row))

        status = row["status"]
        if status in NEEDS_REASON and not (row["decision_reason"] or "").strip():
            err(i, f"{rid}: status={status} требует decision_reason")
        if status in NEEDS_APPLIED_AT and not (row["applied_at"] or "").strip():
            err(i, f"{rid}: status={status} требует applied_at")
        if status in RESPONDED_STATUSES and not (row["response_at"] or "").strip():
            err(i, f"{rid}: status={status} требует response_at")
        if row["decision_reason"] == "other" and not (row["notes"] or "").strip():
            err(i, f"{rid}: decision_reason=other требует пояснения в notes")

        if status == "Duplicate":
            if row["decision_reason"] != "duplicate_listing":
                err(i, f"{rid}: Duplicate требует decision_reason=duplicate_listing")
            match = re.search(r"\bjob-\d{4,}\b", row["notes"] or "")
            if not match:
                err(i, f"{rid}: Duplicate требует id оригинала в notes")
            else:
                duplicate_refs.append((i, rid, match.group(0)))

        if status in NEEDS_APPLIED_AT and (row["stage_reached"] or "None") == "None":
            err(i, f"{rid}: status={status}, но stage_reached=None")
        if row["stage_reached"] == "Offer" and status not in {"Offer", "Rejected", "Withdrawn"}:
            warnings.append(f"строка {i}: {rid}: stage=Offer при status={status}")

        if row["response_at"] and row["applied_at"]:
            try:
                response_date = datetime.strptime(row["response_at"], "%Y-%m-%d").date()
                applied_date = datetime.strptime(row["applied_at"], "%Y-%m-%d").date()
                if response_date < applied_date:
                    err(i, f"{rid}: response_at раньше applied_at")
            except ValueError:
                pass

        cv = (row["cv_version"] or "").strip()
        if status in NEEDS_APPLIED_AT and not cv:
            warnings.append(f"строка {i}: {rid}: отклик без cv_version — аналитика по CV не соберётся")

        if "\n" in (row["notes"] or ""):
            err(i, f"{rid}: перевод строки в notes; длинный текст → applications/{rid}.md")

        # кандидаты в Ghosted
        if status == "Applied" and row["applied_at"] and not row["response_at"]:
            try:
                gap = (date.today() - datetime.strptime(row["applied_at"], "%Y-%m-%d").date()).days
                if gap > GHOST_AFTER_DAYS:
                    warnings.append(f"строка {i}: {rid}: {gap} дней без ответа → status=Ghosted?")
            except ValueError:
                pass

    for canonical_url, entries in urls.items():
        if len(entries) < 2:
            continue
        originals = [(i, r) for i, r in entries if r["status"] != "Duplicate"]
        if len(originals) != 1:
            labels = ", ".join(f"{r['id']}@{i}" for i, r in entries)
            errors.append(f"canonical original_url={canonical_url!r}: ожидается ровно "
                          f"одна оригинальная запись, получено: {labels}")

    for i, rid, original_id in duplicate_refs:
        if original_id == rid:
            err(i, f"{rid}: Duplicate ссылается сам на себя")
        elif original_id not in seen_ids:
            err(i, f"{rid}: оригинал {original_id} не найден")

    return errors, warnings


def ensure_valid(rows):
    errors, warnings = validate_rows(rows)
    if errors:
        die("изменение отклонено:\n  " + "\n  ".join(errors))
    for warning in warnings:
        print(f"warn:  {warning}")


def cmd_validate(args):
    rows = load()
    errors, warnings = validate_rows(rows)

    for w in warnings:
        print(f"warn:  {w}")
    for e in errors:
        print(f"error: {e}", file=sys.stderr)

    print(f"\nпроверено записей: {len(rows)}; ошибок: {len(errors)}; предупреждений: {len(warnings)}")
    if errors:
        sys.exit(1)
    if warnings and args.strict:
        sys.exit(1)


# ---------- dupes ----------

def cmd_dupes(args):
    rows = [r for r in load() if r["status"] != "Duplicate"]
    found = 0
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            cs = similar(norm_company(a["company"]), norm_company(b["company"]))
            if cs < args.threshold:
                continue
            rs = similar(norm_role(a["role"]), norm_role(b["role"]))
            if rs < args.role_threshold:
                continue
            found += 1
            print(f"company {cs:.2f} / role {rs:.2f}")
            print(f"  {a['id']}  {a['company']} — {a['role']}  [{a['status']}]")
            print(f"  {b['id']}  {b['company']} — {b['role']}  [{b['status']}]\n")
    print(f"пар-кандидатов: {found}")
    if found and args.fail:
        sys.exit(1)


# ---------- report ----------

def cmd_report(args):
    rows = load()
    total = len(rows)
    if not total:
        print("jobs.csv пуст")
        return

    def count(pred):
        return sum(1 for r in rows if pred(r))

    print(f"# Отчёт job-searcher — {today()}\n")
    print(f"Всего записей: **{total}**\n")

    print("## Статусы\n")
    print("| Статус | Кол-во |\n|---|---:|")
    for s in STATUSES:
        n = count(lambda r, s=s: r["status"] == s)
        if n:
            print(f"| {s} | {n} |")

    print("\n## Воронка (по stage_reached)\n")
    print("| Стадия | Достигли | % от откликов |\n|---|---:|---:|")
    applied = count(lambda r: (r["stage_reached"] or "None") != "None")
    for s in STAGES[1:]:
        n = count(lambda r, s=s: r["stage_reached"] and
                  STAGES.index(r["stage_reached"]) >= STAGES.index(s))
        pct = f"{n / applied * 100:.0f}%" if applied else "—"
        print(f"| {s} | {n} | {pct} |")

    print("\n## Источники\n")
    print("| Источник | Найдено | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|---:|")
    for src in SOURCES:
        f = count(lambda r, s=src: r["source"] == s)
        if not f:
            continue
        a = count(lambda r, s=src: r["source"] == s and r["applied_at"])
        resp = count(lambda r, s=src: r["source"] == s and r["response_at"])
        rate = f"{resp / a * 100:.0f}%" if a else "—"
        print(f"| {src} | {f} | {a} | {resp} | {rate} |")

    print("\n## Конверсия по match_score\n")
    print("| match_score | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|")
    for label, lo, hi in [("9–10", 9, 10), ("7–8.99", 7, 9), ("5–6.99", 5, 7), ("<5", 0, 5)]:
        def in_bucket(r, lo=lo, hi=hi):
            try:
                return lo <= float(r["match_score"]) < hi or (hi == 10 and float(r["match_score"]) == 10)
            except (ValueError, TypeError):
                return False
        a = count(lambda r: in_bucket(r) and r["applied_at"])
        if not a:
            continue
        resp = count(lambda r: in_bucket(r) and r["response_at"])
        print(f"| {label} | {a} | {resp} | {resp / a * 100:.0f}% |")

    print("\n## Версии CV\n")
    print("| cv_version | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|")
    for cv in sorted({r["cv_version"] for r in rows if r["cv_version"]}):
        a = count(lambda r, c=cv: r["cv_version"] == c and r["applied_at"])
        if not a:
            continue
        resp = count(lambda r, c=cv: r["cv_version"] == c and r["response_at"])
        print(f"| {cv} | {a} | {resp} | {resp / a * 100:.0f}% |")

    print("\n## Причины отсева\n")
    print("| decision_reason | Кол-во |\n|---|---:|")
    for reason in REASONS:
        n = count(lambda r, x=reason: r["decision_reason"] == x)
        if n:
            print(f"| {reason} | {n} |")

    print("\n## Действия к исполнению\n")
    due = sorted((r for r in rows if r["next_action_date"] and
                  r["next_action_date"] <= today()),
                 key=lambda r: r["next_action_date"])
    if not due:
        print("Просроченных действий нет.")
    else:
        print("| Дата | id | Компания | Действие |\n|---|---|---|---|")
        for r in due:
            print(f"| {r['next_action_date']} | {r['id']} | {r['company']} | {r['next_action']} |")


# ---------- CLI ----------

def main():
    p = argparse.ArgumentParser(prog="jobs.py", description="CLI для data/jobs.csv")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="добавить вакансию")
    a.add_argument("--company", required=True)
    a.add_argument("--role", required=True)
    a.add_argument("--source", required=True, choices=SOURCES)
    a.add_argument("--status", default="New", choices=ADD_STATUSES,
                   help="Applied и более поздние статусы ставятся через set")
    a.add_argument("--level", default="Unknown", choices=LEVELS)
    a.add_argument("--remote-policy", dest="remote_policy", default="Unclear", choices=REMOTE)
    a.add_argument("--original-url", dest="original_url")
    a.add_argument("--source-url", dest="source_url")
    a.add_argument("--location")
    a.add_argument("--stack")
    a.add_argument("--salary")
    a.add_argument("--posted-at", dest="posted_at")
    a.add_argument("--found-at", dest="found_at")
    a.add_argument("--match-score", dest="match_score")
    a.add_argument("--decision-reason", dest="decision_reason", choices=REASONS)
    a.add_argument("--notes")
    a.add_argument("--duplicate-of", dest="duplicate_of", metavar="JOB_ID",
                   help="создать Duplicate со ссылкой на оригинальную запись")
    a.add_argument("--no-file", action="store_true", help="не создавать applications/*.md")
    a.add_argument("--force", action="store_true", help="добавить, несмотря на дубли")
    a.set_defaults(func=cmd_add)

    s = sub.add_parser("set", help="изменить запись: jobs.py set job-0001 status=Applied")
    s.add_argument("id")
    s.add_argument("field", nargs="*", help="field=value")
    s.add_argument("--stage", help=f"поднять stage_reached: {', '.join(STAGES)}")
    s.set_defaults(func=cmd_set)

    v = sub.add_parser("validate", help="проверить целостность (для CI)")
    v.add_argument("--strict", action="store_true", help="считать предупреждения ошибками")
    v.set_defaults(func=cmd_validate)

    d = sub.add_parser("dupes", help="fuzzy-поиск дублей")
    d.add_argument("--threshold", type=float, default=0.85, help="порог по company")
    d.add_argument("--role-threshold", dest="role_threshold", type=float, default=0.75)
    d.add_argument("--fail", action="store_true", help="код 1 при находках")
    d.set_defaults(func=cmd_dupes)

    r = sub.add_parser("report", help="markdown-отчёт в stdout")
    r.set_defaults(func=cmd_report)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
```

```bash
chmod +x scripts/jobs.py
```

Примеры использования:

```bash
# найдено на Hirify, сразу отсеяно по гео — 1 команда, 15 секунд
python3 scripts/jobs.py add \
  --company "SomeCo" --role "Frontend Developer" --source Hirify \
  --status Skipped --decision-reason geo_restriction \
  --original-url "https://someco.com/jobs/12" --no-file

# перспективная вакансия: создастся и строка в CSV, и файл в applications/
python3 scripts/jobs.py add \
  --company "ExeQut" --role "Front-End Software Developer" --source Jaabz \
  --original-url "https://www.careers-page.com/exequt/job/RYR3YR7X" \
  --source-url "https://jaabz.com/jobs/253411-front-end-software-developer" \
  --level "Junior/Middle" --remote-policy Unclear \
  --stack "Next.js; TypeScript; REST; CI/CD" --match-score 7.5 --status Reviewing

# подтверждённый дубль: создаст status=Duplicate, reason и ссылку на оригинал
python3 scripts/jobs.py add \
  --company "ExeQut" --role "Frontend Developer" --source LinkedIn \
  --original-url "https://example.com/mirror/exequt-frontend" \
  --duplicate-of job-0001

# отклик отправлен
python3 scripts/jobs.py set job-0001 status=Applied cv_version=frontend-2026-08 \
  next_action=follow-up next_action_date=2026-08-18

# пришёл ответ, назначен скрининг
python3 scripts/jobs.py set job-0001 status=Interviewing response_at=2026-08-12 \
  --stage "Recruiter screen"

# продвинулся по воронке, других полей менять не надо
python3 scripts/jobs.py set job-0001 --stage "Tech interview"

python3 scripts/jobs.py validate
python3 scripts/jobs.py dupes
python3 scripts/jobs.py report > reports/weekly/2026-W32.md
```

### Что уже проверено

Скрипт повторно извлечён из этого документа и прогнан в изолированной временной
структуре после исправления блокеров (Python 3.14.6, macOS). Подтверждено:

- `add` выдаёт последовательные `job-NNNN`, создаёт файл в `applications/` из шаблона, `--no-file` его подавляет;
- дедупликация ловит canonical URL с trailing slash / fragment / `utm_*`, а также `ExeQut` / `EXEQUT Ltd.` + похожую роль; подтверждённый дубль создаётся только через `--duplicate-of`, а отдельная вакансия — через `--force`;
- `dupes` находит именно тот случай из README — `CoinsPaid / Frontend Developer` ≈ `Coins Paid / Software Engineer, Frontend`;
- `set` сам подставляет `applied_at` / `response_at`, поднимает стадию, автоматически переводит `Applied` в `Interviewing`, запрещает понижение и прямую правку `id`, `stage_reached`, `last_update`;
- невалидные дата, `match_score=nan`, `Skipped` без причины и другие нарушения отклоняются **до** атомарной замены CSV; байты исходного файла при ошибке не меняются;
- `add --status Applied` не допускается: исторический отклик добавляется сначала как `New`, затем переводится через `set` с явным `applied_at`;
- предупреждения (не блокируют): отклик без `cv_version`, 30+ дней без ответа → кандидат в `Ghosted`, дата в будущем (защита от опечатки в годе);
- `report` считает воронку, источники, конверсию по `match_score` и по версиям CV, причины отсева и просроченные `next_action`.

Создать `tests/test_jobs.py` на `unittest` + `tempfile` + `subprocess`, без внешних
зависимостей. Зафиксировать в нём перечисленные выше сценарии, включая проверку,
что CSV не меняется после отклонённой команды. Тест запускается так:

```bash
python3 -m unittest discover -s tests -v
```

**Проверка шага:** unittest проходит, а `python3 scripts/jobs.py validate` на пустом
CSV выводит `проверено записей: 0; ошибок: 0` и возвращает код 0.

После успешной проверки зафиксировать write-path одним коммитом:

```bash
git add data applications scripts tests
git commit -m "feat: add jobs schema validated CLI and tests"
```

---

### Шаг 10. `AGENTS.md` — контракт для ИИ-агента

Самый важный файл проекта после `jobs.csv`. Codex читает корневой `AGENTS.md`
автоматически перед работой, поэтому именно здесь должны лежать канонические
правила, а не в README. Файл должен быть коротким и императивным. Основание:
[официальная документация Codex](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

````markdown
# Правила работы с этим репозиторием

Это личный трекер поиска работы. Единственный структурированный источник истины —
`data/jobs.csv`. Схема и допустимые значения: `data/schema.md`. Профиль кандидата:
`config/profile.md`.

## Перед любым поиском вакансий

1. Прочитать `data/jobs.csv` целиком.
2. Прочитать `config/profile.md` (приоритеты, гео, стек, компенсация).
3. Только потом искать новое.

Не анализировать заново вакансию, которая уже есть в CSV. Если она есть:
`Applied` / `Rejected` — не откликаться повторно; `Skipped` — прочитать
`decision_reason`; `Closed` — пропустить; `New` / `Reviewing` — продолжить
предыдущий анализ.

## Железные правила

- **Ни одна найденная вакансия не остаётся без записи.** Закрытая, не подходящая,
  слишком senior, с гео-ограничением — всё равно строка в CSV. Это защита от
  повторного анализа того же самого через неделю.
- **Агрегатор не определяет актуальность.** Перед полным анализом открыть
  первоисточник (careers page, Greenhouse, Lever, Ashby, Workable,
  SmartRecruiters, Teamtailor, BambooHR, Comeet). Закрыто в первоисточнике =
  закрыто, независимо от статуса на агрегаторе.
- **`Remote` сам по себе не значит global remote.** Проверять текст вакансии на
  ограничения по стране и work authorization. Не уверен → `remote_policy=Unclear`.
- **`status=Applied` ставится только после фактической отправки заявки** человеком.
  Агент не отправляет отклики и не ставит `Applied` самостоятельно.
- **Никогда не выдумывать факты о кандидате.** Метрики, должности, стек, срок опыта —
  только из `config/profile.md`. Нет доказательства → не писать.

## Как писать в CSV

- Только через `scripts/jobs.py` (`add` / `set`). Ручная правка — исключение.
- Значения полей — по-английски и строго из enum в `data/schema.md`.
- `id` неизменяем после создания.
- Подтверждённый дубль создавать только через `add --duplicate-of job-NNNN`;
  `--force` означает, что похожая запись является отдельной вакансией.
- Никаких переводов строк в ячейках. Длинный текст → `applications/<id>.md`.
- Разделитель в `stack` — `; `, не запятая.
- После любых изменений: `python3 scripts/jobs.py validate` — должно быть 0 ошибок.

## Порядок обработки одной вакансии

1. dedup-проверка по `data/jobs.csv` (`original_url`, затем company+role);
2. открыть первоисточник, проверить доступность и Apply;
3. hard blockers (гео, work authorization, seniority, закрыто) → сразу
   `add --status Skipped --decision-reason <причина> --no-file`, анализ не проводить;
4. прошло фильтр → полный анализ, `match_score` 1–10, `status=Reviewing`,
   заполнить `applications/<id>.md`;
5. решение `Apply` / `Skipped` / `Closed`;
6. подготовить материалы (CV из `cv/current/`, cover letter, ответы на вопросы формы);
7. человек отправляет заявку → `set <id> status=Applied cv_version=...`.

## Файлы

| Задача | Файл |
|---|---|
| структурированные данные | `data/jobs.csv` |
| длинный контекст по вакансии | `applications/<id>.md` (из `_TEMPLATE.md`) |
| профиль, приоритеты, доказательства | `config/profile.md` |
| резюме для отправки | `cv/current/` (только оттуда) |
| шаблоны сообщений | `templates/outreach.md` |
| недельный отчёт | `reports/weekly/YYYY-Wxx.md` |

Не создавать новые файлы в корне. Не менять схему CSV без обновления
`data/schema.md` и `scripts/jobs.py` в том же коммите.

## Коммиты

Одна логическая операция = один коммит. Формат:

```text
jobs: add job-0042 SomeCo Frontend Developer (Reviewing)
jobs: job-0031 -> Applied
report: week 2026-W32
```
````

Для совместимости с Claude Code создать короткий `CLAUDE.md`, не дублируя контракт:

```markdown
# Project instructions

Перед любой работой прочитать и соблюдать `AGENTS.md`. Он является единственным
каноническим контрактом агента для этого репозитория.
```

---

### Шаг 11. CI

`.github/workflows/validate.yml`:

```yaml
name: validate

on:
  push:
    branches: [main, codex/restructure]
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: '3.12'
      - name: Проверка схемы jobs.csv
        run: python scripts/jobs.py validate
      - name: Unit tests write-path
        run: python -m unittest discover -s tests -v
      - name: Поиск дублей (не блокирует)
        run: python scripts/jobs.py dupes --fail
        continue-on-error: true
```

`validate` блокирует пуш с битыми данными, `dupes` только сообщает — fuzzy-совпадение часто ложное (`Frontend Developer` и `Frontend Engineer` в одной компании могут быть двумя разными вакансиями), и падать на этом нельзя.
Major `v7` сверены 2026-08-09 с официальными README
[`actions/checkout`](https://github.com/actions/checkout) и
[`actions/setup-python`](https://github.com/actions/setup-python); `ubuntu-latest`
использует совместимый GitHub-hosted runner.

Основной workflow зафиксировать отдельно:

```bash
git add .github/workflows/validate.yml
git commit -m "ci: validate jobs data and CLI on push"
```

Опционально (v2) — недельный отчёт по расписанию:

```yaml
name: weekly-report
on:
  schedule:
    - cron: '0 7 * * 1'          # понедельник, 07:00 UTC
  workflow_dispatch:
permissions:
  contents: write
jobs:
  report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: '3.12'
      - run: |
          WEEK=$(date -u +%G-W%V)
          mkdir -p reports/weekly
          python scripts/jobs.py report > "reports/weekly/${WEEK}.md"
      - run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add reports/weekly
          git diff --staged --quiet || git commit -m "report: weekly auto-generated"
          git push
```

---

### Шаг 12. Новый README

README сокращается до навигации (~120 строк). Всё содержательное уже разложено по местам, дублировать нельзя — иначе через месяц снова получится расхождение из раздела 0.1.

Разделы: что это → быстрый старт (3 команды) → структура → куда что писать → ссылки на `AGENTS.md`, `data/schema.md`, `config/profile.md`, `docs/architecture.md`.

Из старого README **обязательно переносится и не теряется**:
- dedup-иерархия (original_url → company+role → similar role) → `AGENTS.md` + `docs/architecture.md`;
- workflow из 8 шагов → `AGENTS.md` (в сжатом виде);
- определения полей и enum → `data/schema.md`;
- принципы и философия → `docs/architecture.md`;
- планы автоматизации (Stage 1–5) → `docs/roadmap.md`.

`docs/roadmap.md` создаётся на этом же шаге, а не остаётся подразумеваемым файлом:

```markdown
# Roadmap

Отложенные этапы автоматизации из прежнего README. Для каждого этапа сохранить:
цель, условие старта, входы/выходы, риски и критерий готовности. SQLite, dashboard,
GitHub Issues intake и внешние API не начинать до стабилизации write-path CSV.
```

Зафиксировать контракт и пользовательскую документацию:

```bash
git add AGENTS.md CLAUDE.md README.md docs
git commit -m "docs: add agent contract and split tracker documentation"
```

---

### Шаг 13. Финальная проверка и пуш

Коммиты уже сделаны сразу после логических этапов, пока индекс содержал только их
изменения. Здесь остаётся общий preflight:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/jobs.py validate
git diff --check
test -z "$(git status --porcelain)"
git push -u origin codex/restructure
```

Затем на GitHub открыть PR `codex/restructure` → `main`, дождаться зелёного CI и
смержить. Локальный merge не использовать: PR оставляет проверяемый diff и результат
workflow. Force-push не требуется.

---

## 5. Ежедневный цикл после развертывания

```text
# начало дня
python3 scripts/jobs.py report | head -40        # что просрочено, где воронка

# сессия поиска (ИИ-агент)
агент читает jobs.csv + config/profile.md
→ ищет на Hirify / Jaabz / LinkedIn
→ по каждой найденной: dedup → первоисточник → hard blockers → add
→ по перспективным: анализ, applications/<id>.md, match_score

# решение человека
отклик отправлен → jobs.py set <id> status=Applied cv_version=...

# конец недели
python3 scripts/jobs.py validate
python3 scripts/jobs.py report > reports/weekly/2026-W33.md
git add reports/weekly/2026-W33.md
git commit -m "report: week 2026-W33" && git push
```

---

## 6. Трудозатраты

| Блок | Оценка |
|---|---|
| Шаги 1–2 (бэкап, ветка, gitignore) | 10 мин |
| Шаг 3 (решение по чужим данным) | 5 мин + ваше решение |
| Шаги 4–5 (структура, перемещения) | 20 мин |
| Шаг 6 (`cv/`) | 30 мин |
| Шаги 7–8 (CSV, schema.md, шаблон) | 30 мин |
| Шаг 9 (`jobs.py` + прогон) | 45 мин |
| Шаг 10 (`AGENTS.md` + указатель `CLAUDE.md`) | 30 мин |
| Шаг 11 (CI) | 15 мин |
| Шаг 12 (README + docs) | 60 мин |
| Шаг 13 (общий preflight, пуш, проверка CI) | 15 мин |
| **Итого** | **≈ 4,5 часа** |

При исполнении агентом — существенно быстрее; основное время уходит на ваши решения по шагам 3 и 6 (какие резюме считать актуальными).

---

## 7. Что сознательно НЕ делаем сейчас

| Отложено | Условие, при котором стоит вернуться |
|---|---|
| SQLite | появился UI, несколько связанных сущностей или конкурентные writers |
| Next.js dashboard | в CSV 50+ записей и данных хватает на графики; тогда же — как portfolio project |
| GitHub Issues как intake | нужен приём вакансий с телефона; Issue → workflow → PR к CSV |
| Zapier / вебхуки | только после стабильного write path через `jobs.py` |
| Greenhouse / Lever API | вручную стало узким местом; у обоих есть публичные GET-эндпоинты, начинать с них |
| LinkedIn API | не начинать: официальный Job Posting API только для одобренных партнёров |

Причина одна: сначала система должна стать **непротиворечивой**, и только потом — сложной. Три конкурирующие схемы в одном репозитории (раздел 0.1) — проблема не автоматизации, а согласованности.

---

## 8. Зафиксированные пользовательские решения

1. `cv/MargaritaSavonevskayaCV.pdf` остаётся в приватном репозитории и переезжает в `cv/archive/`; privacy-риск описан в шаге 3.
2. Единственное актуальное резюме — `evgenii-rubin-cv-08-2026.pdf`; остальные версии CV архивные.
3. Целевой уровень — Junior / Junior+ из-за ограниченного прямого коммерческого опыта продуктовой frontend-разработки.
4. Frontend — основное направление; UI Engineer и Creative Developer используются как дополнительные варианты поиска.
5. Файлы в `cv/archive/` не переименовываются.

Открытых решений, блокирующих шаги 1–13, нет.
