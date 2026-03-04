# Vocab Module — Парсинг словарей ВОВ/ВМВ

## 🎯 Что это

Модуль для автоматического построения специализированных словарей терминов
Великой Отечественной войны из открытых источников (Wikipedia, militera.lib.ru,
rkka.ru, pamyat-naroda.ru и др.).

**Цель:** улучшить распознавание Whisper для редких имён, топонимов, операций,
техники через hotwords + 4-слойную постобработку.

---

## 📦 Что внутри

- **138 живых URL** (из 212 проверенных) — 13 категорий тем
- **58 HIGH-priority** (militera, rkka, pamyat-naroda, iremember)
- **7 парсеров** (Wikipedia, militera, rkka, iremember, warspot, PDF, API)
- **4 этапа обработки** → итог: `data/final_dicts/*.txt` для Whisper

---

## ⚡ Быстрый старт

### 1. Парсинг одного URL (тест)

```bash
python scripts/vocab/parsers/wiki_parser.py \
    --url "https://ru.wikipedia.org/wiki/Список_Героев_Советского_Союза" \
    --category 1 \
    --output-dir data/parsed
Результат: data/parsed/1/ru_wikipedia_org.txt (40–60 терминов)

2. Парсинг всех HIGH-priority URL
bash
python scripts/vocab/run_all_parsers.py --priority HIGH
Время: ~12 минут, результат: data/parsed/{1..13}/ (~2000 терминов до дедупа)

3. Сборка словарей
bash
python scripts/vocab/build_raw_dicts.py   # Этап 2: объединение по категориям
python scripts/vocab/clean_dicts.py       # Этап 3: дедупликация + нормализация
python scripts/vocab/load_vocab.py        # Этап 4A: hotwords для Whisper
Итог: data/final_dicts/*.txt (13 файлов × 100–300 терминов)

📋 Структура документации
Читать в этом порядке:

README.md (ты здесь) — входная точка

ARCHITECTURE.md — структура модуля, этапы 0–4

WORKFLOW.md — полный цикл работы (URL → dict → Whisper)

URL_AUDIT.md — как добавлять новые источники

PARSERS.md — как писать новые парсеры

CHANGELOG.md — история версий

🔗 Связанные документы
data/dictionaries/url_audit.csv — реестр всех источников

tests/simulations/sim_bug_wiki_parser.py — регрессионные тесты парсеров

docs/VALIDATION.md — 8 пунктов проверки (для транскрипции, не для vocab)

Версия: v17.21 (wiki_parser)
Последнее обновление: 2026-03-04