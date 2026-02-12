# Version History

## v16.22 (2026-02-12)
**🐛 FIX БАГ #1 + БАГ #2: Дублирующиеся timestamp + Timestamp назад**

### Изменения:
- **scripts/corrections/timestamp_fixer.py:**
  
  **БАГ #1 (Дубли):**
  - `insert_intermediate_timestamps()`: Добавлена проверка дубля timestamp
  - Regex check: `r'^\d{2}:\d{2}:\d{2}'` → пропускаем вставку, если предложение начинается с HH:MM:SS
  - Debug output: `⏭️ Пропущено дублей: N`
  
  **БАГ #2 (Назад):**
  - `correct_timestamp_drift()`: Проверка монотонности timestamp
  - `if new_start >= old_start` → корректируем только ВПЕРЁД
  - Сдвиг назад → пропускаем корректировку
  - Debug output: `⏭️ ПРОПУСКАЕМ: сдвиг назад -X.Xs`

- **tests/test_timestamp_fixer.py:**
  - Новый класс: `TestCorrectTimestampDrift`
  - Unit test: `test_no_backward_timestamp_movement()` (БАГ #2)
  - Unit test: `test_no_duplicate_timestamps_at_sentence_start()` (БАГ #1)

### Root Cause #1:
- `insert_intermediate_timestamps()` вставляла timestamp БЕЗ проверки дубля
- Результат: `00:00:55 00:00:55 То есть это было...`

### Root Cause #2:
- `correct_timestamp_drift()` сдвигала timestamp НАЗАД
- prev_end = 183.5 → current_start = 186.2 → new_start = 183.5 (назад!)
- Результат: `00:03:06 → 00:03:03` (порядок нарушен)

### Fix #1:
```python
if not re.match(r'^\d{2}:\d{2}:\d{2}', sent.strip()):
    timestamp_str = f" {seconds_to_hms(current_time)} "
    new_text_parts.append(timestamp_str)
Fix #2:
python
if new_start >= old_start:  # Только ВПЕРЁД!
    current_seg['start'] = new_start
    current_seg['time'] = seconds_to_hms(new_start)
Testing:
bash
python -m pytest tests/test_timestamp_fixer.py -v
v16.21 (2026-02-11)
🔧 FIX: Continuation phrase position check (90% → in-split check)