# Weekly reports

Ручные weekly reports `YYYY-Www.md` хранят здесь после weekly review.

Команды только печатают данные в stdout и не создают файл автоматически:

```bash
python3 scripts/jobs.py stats --date YYYY-MM-DD --format json
python3 scripts/jobs.py report --date YYYY-MM-DD
```

`stats` — machine-readable source of truth для итоговых чисел. `report` — его
Markdown-представление для вставки в weekly report; ориентируйтесь на
`templates/weekly-review.md`.
