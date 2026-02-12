# Version History

## v16.22 (2026-02-12)
**🐛 FIX БАГ #1: Дублирующиеся timestamp**

### Изменения:
- **scripts/corrections/timestamp_fixer.py:**
  - `insert_intermediate_timestamps()`: Добавлена проверка дубля timestamp
  - Regex check: `r'^\d{2}:\d{2}:\d{2}'` → пропускаем вставку, если предложение начинается с HH:MM:SS
  - Debug output: показывает пропущенные дубли (`⏭️ Пропущено дублей: N`)

- **tests/test_timestamp_fixer.py:**
  - Новый unit test: `test_no_duplicate_timestamps_at_sentence_start()`
  - Проверяет, что `00:00:55 00:00:55` НЕ появляется

### Root Cause:
- `insert_intermediate_timestamps()` вставляла timestamp БЕЗ проверки, что предложение УЖЕ начинается с timestamp
- Результат: `00:00:55 00:00:55 То есть это было...`

### Fix:
```python
# ПЕРЕД вставкой:
if not re.match(r'^\d{2}:\d{2}:\d{2}', sent.strip()):
    timestamp_str = f" {seconds_to_hms(current_time)} "
    new_text_parts.append(timestamp_str)
Testing:
bash
python -m pytest tests/test_timestamp_fixer.py -v
v16.21 (2026-02-11)
🔧 FIX: Continuation phrase position check (90% → in-split check)