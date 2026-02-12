 🏆 GOLDEN DATASET - Документация

**Версия:** 1.0  
**Создан:** 2026-02-12  
**Статус:** ✅ ACTIVE

---

## 📖 ЧТО ТАКОЕ GOLDEN DATASET

**Golden Dataset** — коллекция эталонных интервью с проверенными транскрипциями для:

1. **End-to-End Regression Testing** — автоматическая проверка качества при каждом изменении кода
2. **Benchmarking** — сравнение версий pipeline
3. **Edge Cases Collection** — база проблемных ситуаций
4. **Documentation** — примеры правильной транскрибации
5. **A/B Testing** — data-driven решения об изменениях

---

## 📁 СТРУКТУРА

golden-dataset/
├── README.md # Описание датасета
├── metadata.json # Метаданные всех интервью
│
├── interview-001-isaev/ # Пример интервью
│ ├── audio/
│ │ └── NW_Uckpa0001_01.wav # Оригинальное аудио
│ ├── json/
│ │ └── NW_Uckpa0001_01.json # JSON с сегментами
│ ├── txt/
│ │ ├── Исаев.txt # Оригинал v16.17
│ │ └── Исаев_proofread.txt # После орфопроверки (эталон)
│ └── metadata.json # Метаданные интервью
│
└── interview-002-xxx/
└── ...

text

---

## 🎯 КРИТЕРИИ КАЧЕСТВА

### ✅ Обязательные требования

**Для добавления в golden dataset:**
- Pipeline версия ≥ v16.17
- Ручная проверка пройдена (manual review: passed)
- Орфографическая проверка выполнена
- Metadata заполнено на 100%
- Длительность 10-90 минут

### 📊 Желательные характеристики

**Разнообразие:**
- Разные спикеры (минимум 5 уникальных)
- Разные темы (история, наука, бизнес, технологии)
- Разные стили (формальный, разговорный)
- Разная аудиокачество (clean, moderate noise)

**Edge Cases:**
- Self-corrections (заикания, повторы)
- Overlapping speech (перебивания)
- Long monologues (>60s)
- Technical terminology
- False positive risks (слова типа "Невы", "совы")

---

## 🧪 ИСПОЛЬЗОВАНИЕ В ТЕСТАХ

### 1. End-to-End Regression Testing

**Файл:** `tests/test_e2e_golden.py`

```python
def test_golden_interview_001_isaev():
    """E2E: Интервью Исаева должен давать стабильный результат"""
    
    # Запуск pipeline
    result = run_full_pipeline(
        "golden-dataset/interview-001-isaev/audio/NW_Uckpa0001_01.wav"
    )
    
    # Загрузка golden output
    golden = load_txt("golden-dataset/interview-001-isaev/txt/Исаев_proofread.txt")
    
    # Проверка similarity
    similarity = text_similarity(result, golden)
    assert similarity > 0.95, f"Similarity {similarity} < 0.95 - REGRESSION!"
    
    # Проверка ключевых точек
    assert "00:01:47" in result, "Missing critical timestamp"
    assert "Исаев: Алексей Исаев" in result, "Speaker attribution failed"
    
    # Проверка edge cases
    assert "Невы" not in find_journalist_segments(result), "False positive: Невы"
Запуск:

bash
pytest tests/test_e2e_golden.py -v
2. Benchmarking новых версий
Файл: scripts/benchmark_golden.py

python
def benchmark_version(version):
    """Запуск всех golden интервью на указанной версии pipeline"""
    
    results = []
    for interview in load_golden_metadata()["interviews"]:
        # Запуск pipeline
        output = run_pipeline(interview["audio"], version=version)
        
        # Сравнение с baseline
        baseline = load_baseline(interview["id"])
        similarity = compare(output, baseline)
        
        results.append({
            "id": interview["id"],
            "similarity": similarity,
            "degradation": 1.0 - similarity
        })
    
    # Генерация отчёта
    generate_report(results)
Запуск:

bash
python scripts/benchmark_golden.py --version v17.0
Вывод:

text
=== BENCHMARK REPORT: v17.0 vs v16.17 ===

interview-001: 98.5% (↓1.5% degradation)
interview-002: 99.2% (↓0.8%)
interview-003: 97.1% (↓2.9% ⚠️ WARNING!)

AVERAGE: 98.3%
REGRESSION DETECTED: interview-003
3. Edge Cases Analysis
Файл: scripts/analyze_edge_cases.py

python
def catalog_edge_cases():
    """Собирает все edge cases из golden dataset"""
    
    catalog = {}
    for interview in load_golden_interviews():
        metadata = load_metadata(interview)
        
        for edge_case in metadata["known_edge_cases"]:
            case_type = edge_case["type"]
            
            if case_type not in catalog:
                catalog[case_type] = []
            
            catalog[case_type].append({
                "interview": interview["id"],
                "timestamp": edge_case["timestamp"],
                "description": edge_case["description"],
                "fixed_in": edge_case["fixed_in"]
            })
    
    return catalog
Вывод:

text
=== EDGE CASES CATALOG ===

self_correction: 3 cases
  - interview-001, 00:02:32 [NOT FIXED]
  - interview-003, 00:15:45 [NOT FIXED]
  - interview-007, 00:31:20 [NOT FIXED]

false_positive_prevented: 5 cases
  - interview-001, 00:01:47 [FIXED v16.16]
  - interview-004, 00:12:33 [FIXED v16.16]
  ...
📊 МЕТРИКИ ДАТАСЕТА
Текущее состояние (v1.0)
| Метрика      | Значение | Цель Q2 2026 |
| ------------ | -------- | ------------ |
| Интервью     | 1        | 20           |
| Длительность | 10 мин   | 800 мин      |
| Спикеры      | 1        | 5+           |
| Темы         | 1        | 5+           |
| Edge cases   | 2        | 50+          |

Качество

| Параметр              | Требование | Статус             |
| --------------------- | ---------- | ------------------ |
| Manual review         | 100%       | ✅ 100%             |
| Proofread             | 100%       | 🔄 0% (в процессе) |
| Metadata completeness | 100%       | ✅ 100%             |
| Pipeline version      | ≥v16.17    | ✅ v16.17           |

📝 ДОБАВЛЕНИЕ НОВОГО ИНТЕРВЬЮ
Пошаговая инструкция
Шаг 1: Транскрибация

bash
python scripts/transcribe.py
# Используй pipeline v16.17+
Шаг 2: Орфопроверка

text
1. Открой txt/Спикер.txt
2. Исправь орфографические ошибки Whisper
3. Сохрани как txt/Спикер_proofread.txt
Шаг 3: Создание структуры

bash
# Замени XXX на номер, surname на фамилию
mkdir -p golden-dataset/interview-XXX-surname/{audio,json,txt}
Шаг 4: Копирование файлов

bash
cp [источник]/audio/file.wav golden-dataset/interview-XXX-surname/audio/
cp [источник]/json/file.json golden-dataset/interview-XXX-surname/json/
cp [источник]/txt/Спикер.txt golden-dataset/interview-XXX-surname/txt/
cp [источник]/txt/Спикер_proofread.txt golden-dataset/interview-XXX-surname/txt/
Шаг 5: Создание metadata.json

bash
# Скопируй template
cp golden-dataset/interview-001-isaev/metadata.json \
   golden-dataset/interview-XXX-surname/metadata.json

# Заполни все поля вручную
nano golden-dataset/interview-XXX-surname/metadata.json
Шаг 6: Обновление golden-dataset/metadata.json

json
// Добавь новую запись в "interviews": [...]
{
  "id": "XXX",
  "folder": "interview-XXX-surname",
  "speaker": "Surname",
  ...
}

// Обнови статистику
"statistics": {
  "total_interviews": 2,  // +1
  ...
}
Шаг 7: Коммит

bash
git add golden-dataset/interview-XXX-surname/
git add golden-dataset/metadata.json
git commit -m "📦 Add golden interview XXX: [Surname] ([Topic])"
git push origin main
🔍 КАТАЛОГ EDGE CASES
Self-Corrections (Заикания, повторы)
Описание: Спикер начинает фразу заново

Примеры:

interview-001, 00:02:32: "Невский пятачок, хотя... Невский пятачок, несмотря..."

(добавляй сюда новые)

Статус: ❌ Не обрабатывается
План: v16.18 — детекция stuttering, вставка "..."

False Positives (Regex)
Описание: Слова ошибочно определяются как маркеры

Примеры:

interview-001, 00:01:47: "Невы" → НЕ журналист ✅ (fixed v16.16)

(добавляй сюда новые)

Статус: ✅ Исправлено в v16.16
Защита: Regression test в test_regex_patterns.py

Long Monologues (>60s)
Описание: Длинные ответы без перебиваний

Примеры:

interview-001, 00:00:21-00:02:27: 126 секунд

(добавляй сюда новые)

Статус: ✅ Корректно обрабатывается
Механизм: Monologue context protection (v16.8)

🚀 БУДУЩЕЕ РАЗВИТИЕ
v16.18+
Детекция self-corrections (stuttering)

Вставка "..." после заиканий

Удаление "Продолжение следует"

v17.0
Первые E2E тесты на golden dataset

Автоматический benchmark при коммитах

v18.0
CI/CD с golden dataset validation

Fine-tuning на golden dataset

Auto-proofread с AI

📞 КОНТАКТЫ
Вопросы по датасету:

GitHub Issues: transcription-project/issues

Документация: docs/

Последнее обновление: 2026-02-12
Версия документа: 1.0