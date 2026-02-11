### ━━━ 2. docs/TESTING-STRATEGY.md ━━━

```markdown
# 🧪 TESTING STRATEGY

Стратегия тестирования проекта транскрибации.

---

## 🎯 ФИЛОСОФИЯ

**Test-Driven Debugging (TDD for Bugs):**
Баг найден → Unit test написан → Фикс создан → Тест прошёл → ✅

text

**Цель:** Каждый найденный баг защищён unit test от повторного появления

---

## 📊 УРОВНИ ТЕСТИРОВАНИЯ

### 1️⃣ Unit Tests (изолированное тестирование функций)

**Что тестируем:**
- ✅ Regex паттерны (`is_journalist_phrase`, `is_expert_phrase`)
- ✅ Text similarity (`text_similarity`)
- ✅ Утилиты (`seconds_to_hms`, `format_timestamp`)
- ✅ Валидаторы (проверка структуры данных)

**Пример:**
```python
# tests/test_regex_patterns.py
def test_journalist_phrase_word_boundary():
    """v16.16: Word boundary protection"""
    # Должны определяться как журналистские
    assert is_journalist_phrase("вы можете объяснить") == True
    
    # НЕ должны (false positives)
    assert is_journalist_phrase("берегу Невы") == False
    assert is_journalist_phrase("совы летают") == False
Запуск:

bash
pytest tests/test_regex_patterns.py -v
2️⃣ Integration Tests (тестирование модулей вместе)
Что тестируем:

✅ Pipeline этапов (diarization → transcription → alignment)

✅ Модули corrections (boundary_fixer → speaker_classifier)

✅ Export (JSON, TXT генерация)

Пример:

python
# tests/test_pipeline.py
def test_split_mixed_segments_sync():
    """v16.12: speaker и raw_speaker_id синхронизированы"""
    segments = [
        {"speaker": "Исаев", "raw_speaker_id": "SPEAKER_01", "text": "Начало. Расскажите подробнее."}
    ]
    
    result = split_mixed_speaker_segments(segments, "Исаев", {"SPEAKER_01": "Исаев", "SPEAKER_00": "Журналист"})
    
    # Проверяем синхронизацию
    for seg in result:
        if seg["speaker"] == "Журналист":
            assert seg["raw_speaker_id"] == "SPEAKER_00", "raw_speaker_id должен быть синхронизирован!"
3️⃣ End-to-End Tests (полный пайплайн)
Что тестируем:

✅ Весь pipeline от WAV → JSON + TXT

✅ Golden output comparison (сравнение с эталоном)

✅ Regression tests (новый код не ломает старое)

Пример:

bash
# tests/test_e2e.py
def test_full_pipeline_expert():
    """Полный пайплайн для тестового файла эксперта"""
    input_wav = "tests/fixtures/expert_sample.wav"
    expected_txt = "tests/golden/expert_sample.txt"
    
    # Запускаем pipeline
    result_txt = run_pipeline(input_wav)
    
    # Сравниваем с golden output
    assert_text_similar(result_txt, expected_txt, threshold=0.95)
🗂️ СТРУКТУРА ТЕСТОВ
text
tests/
├── test_regex_patterns.py      # Unit tests для regex
├── test_text_utils.py           # Unit tests для утилит
├── test_pipeline_modules.py     # Integration tests для модулей
├── test_speaker_attribution.py # Integration tests для атрибуции
├── test_e2e.py                  # End-to-end tests
├── fixtures/                    # Тестовые данные
│   ├── expert_sample.wav
│   ├── journalist_sample.wav
│   └── edge_cases.txt
└── golden/                      # Эталонные результаты
    ├── expert_sample.txt
    ├── expert_sample.json
    └── ...
📋 TEST COVERAGE GOALS
Категория	Текущий Coverage	Цель	Приоритет
Regex паттерны	0%	100%	🔥 Критический
Text utilities	0%	80%	⚠️ Высокий
Speaker attribution	0%	90%	⚠️ Высокий
Pipeline modules	0%	70%	🟡 Средний
Export functions	0%	60%	🟡 Средний
E2E tests	0%	3-5 scenarios	🟡 Средний
🚦 TESTING WORKFLOW
При добавлении новой функции:
text
1. Написать function signature + docstring
2. Написать unit tests (TDD!)
3. Реализовать функцию
4. Запустить tests → GREEN ✅
5. Коммит (код + тесты вместе)
При обнаружении бага:
text
1. Воспроизвести баг (minimal example)
2. Написать failing test (RED ❌)
3. Найти ROOT CAUSE (5 Whys)
4. Исправить баг
5. Запустить test → GREEN ✅
6. Коммит (фикс + тест вместе)
🧪 ПРИМЕРЫ UNIT TESTS
test_regex_patterns.py
python
import pytest
from corrections.boundary_fixer import (
    is_journalist_phrase,
    is_expert_phrase,
    is_continuation_phrase
)

class TestJournalistPhraseDetection:
    """v16.16: Тесты для журналистских фраз"""
    
    def test_positive_cases(self):
        """Фразы, которые ДОЛЖНЫ определяться как журналистские"""
        assert is_journalist_phrase("вы можете объяснить") == True
        assert is_journalist_phrase("расскажите нам подробнее") == True
        assert is_journalist_phrase("давайте обсудим") == True
        assert is_journalist_phrase("как вы считаете") == True
        assert is_journalist_phrase("почему вы выбрали") == True
    
    def test_false_positives_v16_16(self):
        """v16.16 BUG FIX: Слова с 'вы' внутри НЕ должны ловиться"""
        # Root cause v16.16: regex без word boundary
        assert is_journalist_phrase("на восточном берегу Невы") == False
        assert is_journalist_phrase("совы охотятся ночью") == False
        assert is_journalist_phrase("у кровы есть крыша") == False
        assert is_journalist_phrase("правы были все") == False
        assert is_journalist_phrase("называется так") == False
    
    def test_edge_cases(self):
        """Пограничные случаи"""
        # "вы" в конце
        assert is_journalist_phrase("это были вы?") == True
        # "вы" в начале
        assert is_journalist_phrase("Вы уверены?") == True
        # Multiple markers
        assert is_journalist_phrase("вы можете расскажите") == True
        # Empty/None
        assert is_journalist_phrase("") == False
        assert is_journalist_phrase(None) == False

class TestExpertPhraseDetection:
    """Тесты для экспертных фраз"""
    
    def test_positive_cases(self):
        assert is_expert_phrase("я считаю что", "Исаев") == True
        assert is_expert_phrase("на мой взгляд", "Исаев") == True
        assert is_expert_phrase("по мнению Исаева", "Исаев") == True
    
    def test_surname_detection(self):
        """Фамилия эксперта в тексте"""
        assert is_expert_phrase("Исаев утверждает", "Исаев") == True
        assert is_expert_phrase("как сказал Исаев", "Исаев") == True
        # Другая фамилия
        assert is_expert_phrase("Петров считает", "Исаев") == False

class TestContinuationPhraseDetection:
    """v16.10: Тесты для continuation phrases"""
    
    def test_positive_cases(self):
        assert is_continuation_phrase("То есть это важно") == True
        assert is_continuation_phrase("В частности стоит отметить") == True
        assert is_continuation_phrase("Кроме того необходимо") == True
    
    def test_negative_cases(self):
        """НЕ continuation phrases"""
        assert is_continuation_phrase("Это важный момент") == False
        assert is_continuation_phrase("Начнём с того что") == False
test_text_utils.py
python
import pytest
from core.utils import text_similarity, seconds_to_hms

class TestTextSimilarity:
    """v16.5: Тесты для text similarity"""
    
    def test_identical_texts(self):
        assert text_similarity("привет мир", "привет мир") == 1.0
    
    def test_completely_different(self):
        assert text_similarity("привет", "goodbye") < 0.3
    
    def test_partial_similarity(self):
        text1 = "Невский пятачок был плацдармом"
        text2 = "Невский пятачок хотя он располагался"
        similarity = text_similarity(text1, text2)
        assert 0.4 < similarity < 0.7

class TestTimeFormatting:
    """Тесты для форматирования времени"""
    
    def test_seconds_to_hms(self):
        assert seconds_to_hms(0) == "00:00:00"
        assert seconds_to_hms(65) == "00:01:05"
        assert seconds_to_hms(3661) == "01:01:01"
🎯 EDGE CASES COLLECTION
Создаём tests/edge_cases.txt:

text
# Edge Cases для regression testing

## Regex False Positives (v16.16)
- "на восточном берегу Невы предполагалось" → НЕ журналист
- "совы охотятся в темноте" → НЕ журналист
- "у кровы протекает крыша" → НЕ журналист

## Continuation Phrases (v16.10)
- "То есть с небольшого пространства" → продолжение
- "В частности отмечу что" → продолжение
- "Кроме того стоит сказать" → продолжение

## Short Confirmations
- "Да." → короткое подтверждение
- "Ну да." → подтверждение
- "Ага." → подтверждение

## Question Announcements
- "Следующий вопрос про Ленинград" → анонс (не разделять)
- "Ещё вопрос о блокаде" → анонс

## Overlapping Speech
- Журналист перебивает эксперта
- Короткие вставки (<0.5s)
🚀 CONTINUOUS INTEGRATION (будущее)
Цель: Автоматический запуск тестов при каждом коммите

text
# .github/workflows/tests.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.10
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run unit tests
        run: pytest tests/ -v --cov
      - name: Coverage report
        run: coverage report --fail-under=80
📈 METRICS & GOALS
Количественные цели:
Unit test coverage: 0% → 80% (за Q2 2026)

Regression tests: 0 → 20 edge cases

Bug reproduction time: 5.5 часов → <30 мин

Iterations to fix: 8 → ≤3

Качественные цели:
✅ Каждый баг защищён unit test

✅ Regression suite для всех критических функций

✅ Golden output для end-to-end comparison

✅ CI/CD pipeline с автоматическими тестами

Последнее обновление: 11.02.2026
Версия: v16.17