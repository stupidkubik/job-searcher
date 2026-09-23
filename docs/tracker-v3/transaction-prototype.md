# V3 multi-file transaction prototype

Статус: WP1.3a prototype проверен 2026-09-23; с 2026-09-24 текущий
`tracker_write.py` публикует CSV и изменяемые application cards через этот
журнал. Event ledger, connector result и generated views ещё не входят в
publication set. B-003 остаётся открыт.

## Что обнаружено в существующем пути

`tracker_write.apply_dataset_transaction` использует `.ingest.lock`, готовит
CSV/card и последовательно вызывает `os.replace`. При Python exception он
откатывает заменённые файлы. После process kill посередине цикла lock
освобождается ОС, но rollback не запускается. `agent_operations.py` пишет
immutable result после canonical write, а `scripts/ci/apply_operation.sh`
рендерит tracker/index ещё позже. Нынешние read commands не держат общий lock
при чтении этих файлов. Поэтому добавление event file к старому циклу само по
себе не обеспечит B-003.

## Проверенный протокол прототипа

`tracker_transaction.publish(root, writes, expected)` принимает полный набор
байтов будущих файлов и SHA-256 прежних версий. Под одним file lock он:

1. восстанавливает предыдущее прерванное действие, если оно есть;
2. сравнивает expected revisions с текущими байтами (stale operation
   отвергается до записи);
3. сохраняет старые и новые байты в журнале, затем fsync файлов, manifest и
   директории журнала;
4. заменяет каждый target, fsync его директории и вызывает callback проверки;
5. записывает durable `committed` marker;
6. атомарно переименовывает журнал из pending в finished и удаляет его.

Если процесс завершается до marker, `recover()` повторяемо восстанавливает
все старые байты. Если marker уже durable, recovery сохраняет новые байты.
Reader, который использует `read_consistent()`, вызывает recovery и читает
набор под тем же lock. Если cleanup прервётся, finished directory можно удалить
позже, не открывая уже завершённую транзакцию заново. Испорченная backup copy
останавливает recovery с ошибкой вместо молчаливого частичного отката.

| Точка остановки | Следующее recovery |
|---|---|
| До manifest | удаляет подготовительный журнал; targets не менялись |
| После manifest, до/между заменами | восстанавливает каждый старый target; новые ранее отсутствовавшие удаляет |
| После всех замен, до durable marker | откатывает весь набор |
| После durable marker | сохраняет весь новый набор и завершает cleanup |

Тесты `tests/test_tracker_transaction.py` запускают дочерний процесс и
принудительно завершают его после подготовки, после каждой из пяти замен и
после commit marker. Они также проверяют обычные exceptions, failed validation,
повторное recovery, corrupt backup, stale revision и гонку двух процессов.
Набор включает synthetic event, snapshot CSV, generated index/view и operation result, чтобы
продемонстрировать нужную transaction boundary. Ни один тест не использует
production `jobs.csv`.

## Что требуется до включения в write path

1. Объединить `.ingest.lock` и prototype lock в один lock для всех writers.
   С 2026-09-24 `apply_dataset_transaction` использует prototype lock и
   восстанавливает pending journal перед заменой файлов; тесты проверяют
   взаимное исключение двух путей и recovery. Остальные writers, в том числе
   прямые maintenance `save`/`save_job_sources`, ещё требуют аудита. С
   2026-09-24 `add`/`set`/`status`/`screen`/`verify`/`ingest` и connector batch
   берут согласованный base snapshot и сравнивают SHA-256 обоих CSV под lock
   перед заменой. Устаревшая подготовка отвергается; connector возвращает
   `conflict` с retry-фрагментом. С 2026-09-24 изменяемые application cards
   также сверяются по SHA-256 (или отсутствию файла) перед заменой, включая
   batch workspace. Прямые ручные правки карточки вне общего lock во время
   самой публикации всё ещё требуют отдельной политики.
2. Все читатели согласованного набора (snapshot/event/result и нужные generated
   views) должны сначала выполнять recovery и читать под этим lock либо через
   доказанный versioned snapshot. Сейчас только prototype `read_consistent()`
   соблюдает это правило.
3. Сформировать и валидировать future snapshot, event, card, result и
   необходимые projections **до** публикации. Connector result должен входить
   в тот же `writes` set или иметь проверяемое восстановление; нынешний
   `write_result()` выполняется позже. Runner allowlist и `git add` должны
   явно включить event path, но никогда journal/lock.
4. Проверить process crash/fault boundary уже на интегрированной операции,
   включая generation failure, stale connector retry и race с job operation.
   Отдельный prototype не доказывает эти свойства production кода.
5. Провести dry-run и rollback rehearsal на временной копии актуального
   dataset, затем только отдельным cutover commit включать canonical event
   writes. B-005 historical migration остаётся самостоятельным gate.

Журнал содержит старые байты, в том числе персональные данные. Его пути
игнорируются Git; после crash он должен быть локальным и доступным только
владельцу checkout. Права 0700/0600 проверяются тестом; для event cutover ещё
нужна политика срока хранения abandoned finished directories.

## Интеграция 2026-09-24

`apply_dataset_transaction` формирует полные байты jobs/source CSV и карточки,
передаёт исходные SHA-256 в `publish()` и проверяет итоговый dataset до durable
commit marker. CLI восстанавливает pending journal перед командой; read-only
команды держат общий lock на время чтения. Connector runner тоже восстанавливает
журнал перед обработкой request.

Интеграционный CLI-тест обрывает `verify` до первой замены и после каждой из
трёх замен (card + два CSV), затем запускает `validate --strict` и проверяет
полное восстановление исходных байтов. Это защищает текущую canonical пару и
карточку. Connector result, index/tracker projections и event artifact пока
публикуются отдельно или ещё не пишутся; поэтому Gate 1 не пройден.
