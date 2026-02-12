# Version History

## v16.22 (2026-02-12)
**🐛 FIX БАГ #1 + БАГ #2 + БАГ #3: Timestamp дубли + Timestamp назад + Loop artifacts**

### Изменения:
- **scripts/corrections/timestamp_fixer.py:**
  
  **БАГ #1 (Дубли timestamp):**
  - `insert_intermediate_timestamps()`: Проверка дубля перед вставкой
  - Regex: `r'^\d{2}:\d{2}:\d{2}'`
  
  **БАГ #2 (Timestamp назад):**
  - `correct_timestamp_drift()`: Проверка монотонности
  - `if new_start >= old_start` → только ВПЕРЁД

- **scripts/merge/replica_merger.py:**
  
  **БАГ #3 (Loop artifacts с вариациями):**
  - `clean_loops()`: Fuzzy matching для детекции вариаций
  - SequenceMatcher: similarity ≥75% → считаем повтором
  - Было: только точные повторы → Стало: детекция вариаций слов

- **tests/test_timestamp_fixer.py:**
  - Unit tests для БАГ #1, БАГ #2

- **tests/test_replica_merger.py:**
  - Новый файл: unit test для БАГ #3
  - `test_remove_loop_with_word_variations()` - детекция вариаций

### Root Cause #1:
- `insert_intermediate_timestamps()` вставляла timestamp БЕЗ проверки дубля
- Результат: `00:00:55 00:00:55 То есть это было...`

### Root Cause #2:
- `correct_timestamp_drift()` сдвигала timestamp НАЗАД
- Результат: `00:03:06 → 00:03:03` (порядок нарушен)

### Root Cause #3:
- `clean_loops()` детектировала только ТОЧНЫЕ повторы 3-словных фраз
- Вариации ("была" → "было", "вправь до" → "вплоть до") НЕ детектировались
- Результат: 3 вариации одной фразы остаются в TXT

### Fix #1:
```python
if not re.match(r'^\d{2}:\d{2}:\d{2}', sent.strip()):
    timestamp_str = f" {seconds_to_hms(current_time)} "
    new_text_parts.append(timestamp_str)
Fix #2:
python
if new_start >= old_start:  # Только ВПЕРЁД!
    current_seg['start'] = new_start
Fix #3:
python
for prev_phrase in seen:
    similarity = SequenceMatcher(None, phrase_lower, prev_phrase).ratio()
    if similarity >= 0.75:  # Похожесть ≥75%
        is_loop = True
        break
Testing:
bash
# БАГ #1, #2:
python -m pytest tests/test_timestamp_fixer.py -v

# БАГ #3:
python -m pytest tests/test_replica_merger.py -v
v16.21 (2026-02-11)
🔧 FIX: Continuation phrase position check (90% → in-split check)