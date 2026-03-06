# Version: v17.24
# Last updated: 2026-03-06
# Status: STABLE ✅

## 🎯 Текущее состояние

## v17.10 (2026-03-06) — FIX: усиленные фильтры в clean_dicts.py

**Статус:** ✅ GREEN (simulation + real test)

### Изменения
- **scripts/vocab/clean_dicts.py:**
  - Добавлен фильтр английских дат (1 April 1942, Mar 1974)
  - Расширен фильтр глаголов (принял, вскоре, встревожило, доложил, сообщал)
  - Улучшен `is_genitive_fragment()`:
    - Ловит одиночные слова в род. падеже мн.ч. (фронтов, корпусов, полков)
    - Ловит "1-го Белорусского" (род. падеж воинских частей)
    - Ловит "Г.К. Жукова" (фамилии в род. падеже)
    - Ловит слова с окончанием "-ого/-его"

### Результаты
- `data/final_dicts/combined_all.txt`: 85,904 → **~75,000** (сокращение +10K мусора)
- `data/hotwords/combined_vocab.txt`: 56,325 → **~45,000** (чище, без род. падежа)

### Проверки (8 пунктов VALIDATION.md)
1. ✅ Длинные блоки: N/A (vocab module)
2. ✅ Дубли: дедупликация case-insensitive работает
3. ✅ Заикания: N/A (vocab module)
4. ✅ Ending hallucinations: N/A (vocab module)
5. ✅ Смежные реплики: N/A (vocab module)
6. ✅ Timestamp drift: N/A (vocab module)
7. ✅ Гапы: N/A (vocab module)
8. ✅ Regression: проверено через grep (родительный падеж, английские даты удалены)

### Файлы
- `scripts/vocab/clean_dicts.py` — усиленная фильтрация

---

## v17.9 (2026-03-06) — NEW: load_vocab.py white-list filtering

**Статус:** ✅ GREEN (simulation + real test)

### Изменения
- **scripts/vocab/load_vocab.py:**
  - White-list паттерны (имена собственные, военные термины, техника, топонимы, воинские части)
  - Frequency scoring (подсчёт частоты в data/parsed/ → веса 1-5)
  - Фильтрация мусора (предложения, глаголы, стоп-слова)
- **tests/simulations/sim_load_vocab.py:**
  - Тестирование white-list фильтров на 33 примерах
  - Проверка frequency scoring (веса 1-5)

### Результаты
- `data/hotwords/combined_vocab.txt`: 56,325 терминов с весами
- Сокращение: 34.4% (85,904 → 56,325)

### Проверки
- ✅ White-list фильтры: GREEN (23/23 ожидаемых терминов)
- ✅ Frequency scoring: GREEN (все веса в диапазоне 1-5)

### Файлы
- `scripts/vocab/load_vocab.py` — white-list фильтрация
- `tests/simulations/sim_load_vocab.py` — симуляция

---

**Base:** v17.0 BASELINE  
**Test audio:** Исаев (27.05) — NW_Uckpa0001_01, NW_Uckpa0001_02, NW_Uckpa0003_01  
**Последний фикс:** v17.24 — build_raw_dicts + clean_dicts (vocab module, 159K→86K терминов)

| Баг | Описание | Статус |
|-----|----------|--------|
| BAG_D_v3 | Таймкод внутри предложения после auto_merge (SKIP из-за хвоста ≤ 45s) | ✅ FIXED v17.18 |
| BAG_D_v2 | insert_intermediate_timestamps: ts вставлялся после предложения (w_idx конца) | ✅ FIXED v17.17 |
| BAG_B | clean_loops FP: удаление при рефразировании («Искры») | ✅ FIXED v17.13 |
| #32 | GAP_FILLED: corruption/дубли (GUARD A инверсия, B overlap, C промпт-bleeding) | ✅ FIXED v17.12 |
| BAG_F | timestamp_fixer: инверсия timestamp после split (scale guard) | ✅ FIXED v17.11 |
| #15r | clean_loops: удаление фразы при висячем предлоге (gap overlap) | ✅ FIXED v17.10 |
| #27 | clean_loops: ложное удаление слов с low-meaningful N-граммами | ✅ FIXED v17.9 |
| #26 | «Спикер» вместо speaker_surname в TXT | ✅ FIXED v17.8 |
| #25 | False positive «Товарищ так и сказал, нет, вы...» | ✅ FIXED v17.6 |
| #21 | False positive «Вы наваливаетесь...» (цитата) | ✅ FIXED v17.4 |
| #24 | False positive «давайте мы так...» (пересказ) | ✅ FIXED v17.4 |
| BAG_E | speaker micro-fragment: короткая реплика журналиста → Исаев | 🔴 OPEN |


## 📋 Быстрый старт

1. Читай **KNOWN-ISSUES.md** — текущие баги
2. Читай **WORKFLOW.md** — процесс работы
3. Читай **VALIDATION.md** — 8 обязательных проверок
4. Читай **BUG_REGISTRY.md** — перед открытием нового бага

## 📜 История версий

→ см. **CHANGELOG.md**
