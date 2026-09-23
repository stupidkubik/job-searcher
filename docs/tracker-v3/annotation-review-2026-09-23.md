# Tracker v3 — разбор пометок к open issues

Дата: 2026-09-23. Это design review, а не изменение действующих контрактов или
разрешение phase gate. `+` в исходных пометках означает согласие с направлением;
итоговый `match_score` выставляет агент. Основание: пометки в `open-issues.md`, текущие
`tracker_write.py`, `agent_operations.py`, `data/schema.md` и baseline v3.

## Event ledger: B-001–B-005

**B-001, хранение.** Предпочтительный вариант для первого прототипа —
`data/application_events/job-NNNN.jsonl`: один файл на job, одна JSON-строка на
event. Обычный поиск читает только нужный job; агенту не нужен общий ledger при
bootstrap. Один глобальный JSONL станет конфликтным файлом для всех операций;
отдельный JSON на каждое событие увеличит число файлов и работу с Git. Путь,
порядок строк и запрет переписывания существующего префикса нужно закрепить в
D-003 после прототипа на 1k/10k synthetic events. Прототип должен измерить
полный scan, выборку одного job, размер, число файлов, Git diff и влияние на
транзакцию. Без этих измерений B-001 остаётся открытым.

**B-002, identity и исправления.** Предпочтение: caller передаёт устойчивый
idempotency key; connector выводит его из `operation_id` и `client_ref`, локальный
CLI принимает явный key. `event_id` не выводится только из содержимого:
одинаковые интервью или follow-up могут быть разными событиями. Audit order
задают `recorded_at` (UTC instant) и `event_id` как tie-breaker; `occurred_at`
может иметь точность `date`, `instant` или `unknown` и не обязан совпадать с
порядком записи. Исправление — новое полное событие с `supersedes`; исходная
строка не меняется. Исправление может менять тип, время и payload, иначе нельзя
исправить ошибочно выбранный event type. Ссылка допустима только на ранее
записанное событие того же job; цепочки и retry проверяет validator. Это ещё
требует fixtures на одинаковые timestamps, циклы и повторную отправку.

**B-003, граница записи и нагрузка на агента.** Снаружи должна быть одна
авторизованная операция с одним результатом. Агент и connector не должны
делать последовательные вызовы «записать событие» и «обновить snapshot» или
сами перегенерировать индексы. Внутри write service под одним lock строит
будущую строку CSV, event, application card и обязательные projections,
проверяет их, затем публикует как один логический commit. Сейчас
`apply_dataset_transaction` заменяет файлы по очереди и откатывает при
исключении; аварийное завершение между `os.replace` не покрыто этим откатом.
Перед dual-write нужен durable transaction journal с автоматическим recovery
до любого чтения/записи затронутых данных либо иной доказанный протокол
публикации. Обычные fault-injection тесты недостаточны: нужны kill/crash tests
для каждого рубежа, повтор операции и проверка, что connector result соответствует
восстановленному canonical state. До такого доказательства B-003 не закрыт.

**B-004, минимальная таксономия.** Для отдельного анализа разделяем факт и
snapshot-проекцию. Предлагаемый начальный набор:

| Семейство | События v3 core | Проекция в текущий snapshot |
|---|---|---|
| Отправка | `application_submitted` | `applied`, `Applied`, `applied_at` |
| Ответ | `acknowledgement_received`, `response_received` | `response_at` только при содержательном ответе; acknowledgement отдельно |
| Этап | `assessment_invited`, `assessment_completed`, `interview_scheduled`, `interview_completed`, `interview_cancelled` | достигнутый этап растёт при приглашении/назначении; отмена не стирает достигнутый этап |
| Итог | `offer_received`, `rejection_received`, `candidate_withdrew`, `no_response_closed` | соответственно `offer`, `rejected`, `withdrawn`, `ghosted` |
| Действие | `follow_up_sent` | не меняет lifecycle |

Для нескольких интервью `interview_*` несёт `round_id` и `round_kind` из
`recruiter|technical|final|other`; перенос — новое `interview_scheduled` с тем
же `round_id`, а не изменение старого события. У `assessment_*` тоже нужен
устойчивый `assessment_id`. `response_at` — дата первого содержательного ответа;
отказ сам является таким ответом. `assessment_invited` проецируется на
`Test task`, но оставляет `application_status=applied`; `interview_scheduled`
или `interview_completed` переводит его в `interviewing`. Recruiter/technical/
final round соответствует `Recruiter screen`/`Tech interview`/`Final interview`;
`other` требует явно указанного `stage_hint` из существующего enum.
`stage_reached` — максимум эффективных событий и не снижается при обычном
отказе или отмене. Исправление ошибочного события может законно уменьшить
этот максимум: это специальная операция пересчёта, для которой нынешний
монотонный setter непригоден. Событие `no_response_closed` требует
подтверждения человека, как и другие lifecycle переходы. Эти правила надо
проверить на десяти сценариях из verification matrix и принять до WP1.1.

Проверка смысла проекции на обязательных сценариях (даты в таблице условные;
fixtures ещё не созданы):

| Сценарий | Ожидаемый effective snapshot |
|---|---|
| Submit без ответа | `applied`, `Applied`, `applied_at` есть, `response_at` пуст |
| Ack → recruiter interview → rejection | `rejected`, `Recruiter screen`; первый содержательный ответ задаёт `response_at`, ack не задаёт |
| Assessment → technical interview → offer | `offer`, `Offer`; отдельные assessment/interview events сохраняют пройденные шаги |
| Interview перенесён и завершён | `interviewing`, stage соответствующего round; прежнее назначение остаётся в audit history |
| Withdrawal до ответа | `withdrawn`, `Applied`; `response_at` пуст |
| Ошибочный rejection исправлен | пересчёт effective status и stage из оставшихся событий; исходный rejection виден как superseded |
| Listing закрыт после Submit | application lifecycle не меняется; `listing_status` ведётся отдельно |
| Несколько source URL одного job | одна timeline по canonical `job_id` |
| Legacy applied с датой | `applied_at` остаётся date-only, точный instant неизвестен |
| Hypothetical письмо из inbox | event не появляется без review и подтверждения |

Эта таблица выявляет два обязательных специальных правила: correction может
уменьшить ошибочный исторический максимум, а `acknowledgement_received` не
считается содержательным ответом. Принять таксономию можно после создания
fixtures и проверки этих правил кодом; до этого B-004 остаётся investigating.

**B-005, historical precision.** В нынешних 458 строках: 37 `applied` с
`applied_at` и без `response_at`; 8 `rejected` с обеими датами и
`stage_reached=Applied`; другие 413 строк не содержат lifecycle дат. Поэтому
dry-run backfill может предложить 45 `application_submitted` и 8
`rejection_received`, все с `precision=date`, `source=migration`; он не должен
создавать фиктивные интервью, точные часы или отдельный `response_received`
для тех же отказов. Если даты совпадают, порядок задаёт известная причинность
и стабильный migration ID, а не придуманное время суток. Будущая таблица
миграции обязана покрыть все допустимые состояния схемы, а не только этот
snapshot; до dry-run и повторного прогона B-005 остаётся открытым.

## Packet, matching, branch: Q-006–Q-012

- **Q-006.** Безопасный путь — версионированные manifests под
  `applications/job-NNNN/packets/<packet-id>.json`. Плоские application cards
  продолжают работать до отдельной миграции ссылок и rollback rehearsal. Новый
  packet не перемещает карточку сам по себе. Так можно подготовить несколько
  вариантов без перезаписи и без массового переименования файлов в
  `applications/`. Точные правила ID/lookup ещё нужны до WP2.1.
- **Q-007.** Hash охватывает raw bytes каждого source/derived artifact отдельно;
  для отсутствующего cover letter используется явное `none`, а missing file —
  ошибка проверки. Решение принимается вместе с packet schema.
- **Q-008.** Для первого прототипа выбрать явные стабильные evidence IDs рядом
  с фактами в `config/profile.md`. Sidecar создаст вторую синхронизируемую
  структуру; номер строки или текстовый hash ломается при редактировании.
  Удаление/слияние фактов требует tombstone/alias и проверки ссылок. До
  прототипа validator вопрос остаётся открытым.
- **Q-009.** Существующий `match_score` — сохранённая оценка агента, а не
  автоматически вычисляемый факт. Для v3 нужен versioned assessment с
  требованиями, evidence, eligibility, confidence и явно записанным итоговым
  баллом/обоснованием агента. Код проверяет диапазон, ссылки, hard blockers и
  воспроизводимость уже сохранённого artifact; автоматическую формулу scoring
  нельзя вводить без отдельного решения и golden corpus. Старые баллы остаются
  legacy без доказательств. Это требует согласования с D-005/WP3.3.

  | Состояние | Правило совместимости |
  |---|---|
  | Старый непустой `match_score`, match artifact отсутствует | Сохранить число без изменения; показывать как legacy assessment с неизвестной версией/evidence |
  | Старый пустой `match_score` | Оставить пустым до новой оценки агента |
  | Новый versioned assessment | Агент явно записывает балл и rationale; snapshot `match_score` получает этот же балл через авторизованный write path |
  | Агент пересмотрел оценку | Создать новую версию artifact и обновить snapshot; предыдущая версия остаётся доступной |

- **Q-010.** Сохраняем merge checkpoints без force-push и production migration
  только от свежего `main`. На момент обзора `codex/tracker-v3` на два commit
  впереди `origin/main` и не отстаёт от него; перед cutover измерение повторить.
- **Q-011.** Новое событие должно идти через существующий trusted runner и
  generated contract. Форму команды (`event` или расширение `status`) выбираем
  после event schema; v1 requests остаются читаемыми, stale/retry семантика
  обязательна. Это не дополнительный ручной шаг для агента.
- **Q-012.** Не добавлять новый обязательный bootstrap-файл заранее. Для
  конкретного job нужен targeted read (`timeline JOB_ID`, `packets JOB_ID`,
  `match JOB_ID`); общие индексы делать только для полей, требуемых `todo`,
  дедупом или generated tracker. На каждом gate измерять изменение байтов
  обязательного bootstrap-набора и время targeted read. Граница — обычный
  bootstrap не читает весь event/packet/match corpus. Реальные измерения
  возможны после прототипа, поэтому Q-012 остаётся открытым.

## Поздние фазы: Q-013–Q-016

- **Q-013.** Почта и browser session доступны только локальному агенту через
  разрешённый credential store/session. Токены и raw messages не хранятся в
  Git, application cards, CI artifacts или operation results. Repo может
  содержать код reader и synthetic/redacted fixtures. Секреты CI допустимы
  только если отдельным решением действительно потребуется CI-доступ к почте;
  текущая Phase 5 такого доступа не требует.
- **Q-014.** Вопрос хранения отклонённых proposals остаётся на Phase 5:
  сначала offline fixtures и privacy review, затем срок хранения и минимальный
  audit record. Знак `+` не является готовой retention policy.
- **Q-015.** Inventory текущего `jobs.csv` для решения вопроса контактов:
  458 jobs, `contact_name` заполнен в 0 строках, `contact_url` в 0 строках.
  Сейчас не вводим отдельную contact graph/schema; используем существующие
  поля и карточки. Вернуться к вопросу при реальных повторяющихся контактах
  или workflow, которому нужна связь одного контакта с несколькими job.
- **Q-016.** Browser assistance остаётся отложенной до Phase 8. Перед её
  началом отдельно подготовить packet contract, threat model, permission
  review и оценку поддержки; final Submit остаётся за человеком.
