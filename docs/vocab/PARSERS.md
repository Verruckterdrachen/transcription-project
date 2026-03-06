# Vocab Module — Написание парсеров

## 🧩 Template: BaseParser

Все парсеры наследуются от `BaseParser` (Template Method паттерн):

```python
from scripts.vocab.parsers.base_parser import BaseParser

class MyParser(BaseParser):
    def fetch(self) -> str:
        """Скачать HTML/JSON/PDF. Использовать cache + retry."""
        pass

    def extract_terms(self, content: str) -> list[str]:
        """Извлечь термины из контента. Вернуть список строк."""
        pass

    # save() уже реализован в BaseParser
Шаблон автоматически:

Создаёт output_dir/{category}/

Сохраняет в {domain}.txt (1 термин = 1 строка)

Логирует прогресс

Обрабатывает ошибки

📚 Примеры реализации
1. wiki_parser.py — Wikipedia (готов v17.21)
Стратегии:

_extract_from_tables() — wikitable (сканирует cells[0..2])

_extract_from_lists() — ul/li элементы

_extract_from_headings() — h2/h3 заголовки

Особенности:

ru.wikipedia: кириллица (все стратегии)

en.wikipedia:

Primary: кириллица из скобок "Georgy Zhukov (Георгий Жуков)"

Secondary: латиница ТОЛЬКО техника/аббревиатуры (Panzer-IV, StuG, Tiger I)

Discard: транслитерации (Georgy Zhukov)

Нормализация:

_clean_term(): убирает [[...]], сноски, скобки с русским текстом

_normalize_caps(): ЖУКОВ → Жуков, но ГДР/СССР не трогать (≤4 chr)

_is_useful_latin(): фильтр латиницы (цифры + буквы, римские числа, не стоп-слова)

Real test результаты:

ru/Список_Маршалов_Советского_Союза → 42 термина ✅

en/Marshal_of_the_Soviet_Union → 0 (нет кириллицы в скобках — ожидаемо)

Симуляция: tests/simulations/sim_bug_wiki_parser.py (60/60 GREEN)

## 2. militera_parser.py — militera.lib.ru (готов v17.22)

Двухуровневый crawler:

**Level 0 — index.html:**
- Автор книги из `<title>` / header
- TOC ссылки (топонимы/операции из названий глав)
- Выход: ~20 терминов

**Level 1 — chapter pages (max 15 страниц):**
- 4 паттерна без NER:
  1. `_extract_rank_names()`: `(генерал|маршал|адмирал)\s+([А-ЯЁ][а-яё]+...)`
  2. `_extract_quoted_terms()`: текст в `«»`
  3. `_extract_unit_names()`: `(\d+)?\s*(танковая группа|фронт|армия|корпус)`
  4. `_extract_cap_sequences()`: 2–5 слов с заглавной (не после точки)
- Выход: ~30–60 терминов/глава

**Итого:** ~500–600 терминов/книга (с дублями Level 0 + Level 1)

**Нормализация:**
- `_normalize_case()`: приводит косвенные падежи к именительному
- Импортирует `_clean_term()` из `wiki_parser` (фильтрация мусора)
- `_dedupe_ordered()`: case-insensitive дедупликация

**Rate limit:** 2 сек/запрос (вежливость к статическому серверу)

**Real test результаты:**
- `memo/russian/rokossovsky/index.html` → 3765 терминов ✅
- Симуляция: `tests/simulations/sim_militera_parser.py` (53/53 GREEN)

**Известные проблемы:**
- `_extract_cap_sequences()` извлекает много шума из нарративного текста ("Годы шли", "Было ясно")
- Рекомендация: отключить для мемуаров, оставить только для справочников

Выход: ~20 терминов

Level 1 — chapter pages (max 15 страниц):

4 паттерна без NER:

_extract_rank_names(): (генерал|маршал|адмирал)\s+([А-ЯЁ][а-яё]+...)

_extract_quoted_terms(): текст в «»

_extract_unit_names(): (\d+)?\s*(танковая группа|фронт|армия|корпус)

_extract_cap_sequences(): 2–3 слова с заглавной (не после точки)

Выход: ~30–60 терминов/глава

Итого: ~500–600 терминов/книга

Rate limit: 2 сек/запрос (вежливость к статическому серверу)

3. api_parser.py — pamyat-naroda.ru (будущее)
Особенности:

REST API (JSON)

Rate limit: 0.5 req/sec (документация API)

Пагинация (iterator до exhaustion)

Пример:

python
def fetch(self) -> str:
    data = []
    page = 1
    while True:
        self.rate_limiter.wait(self.domain)  # 2 сек (0.5 req/s)
        resp = self.session.get(f"{API_URL}?page={page}")
        batch = resp.json()
        if not batch["items"]:
            break
        data.extend(batch["items"])
        page += 1
    return json.dumps(data)
🛠️ Вспомогательные функции (переиспользуй)
Нормализация КАПСЛОК
python
from scripts.vocab.parsers.wiki_parser import _normalize_caps

text = _normalize_caps("ВОРОШИЛОВ КЛИМЕНТ")
# → "Ворошилов Климент"

text = _normalize_caps("СССР ГДР НКВД")  # аббревиатуры ≤4 chr не трогаем
# → "СССР ГДР НКВД"
Дедупликация с сохранением порядка
python
from scripts.vocab.parsers.wiki_parser import _dedupe_ordered

terms = ["Жуков", "Сталин", "жуков", "СТАЛИН", "Жуков Г.К."]
result = _dedupe_ordered(terms)  # case-insensitive, first occurrence wins
# → ["Жуков", "Сталин", "Жуков Г.К."]
Фильтр имён
python
def _is_person_name(term: str) -> bool:
    """Возвращает True если термин похож на ФИО."""
    tokens = term.split()
    if len(tokens) < 2 and not re.search(r'[А-ЯЁ]\.\s*[А-ЯЁ]\.', term):
        return False  # минимум 2 токена ИЛИ инициалы
    if not re.match(r'[А-ЯЁ]', tokens):
        return False  # первый токен с заглавной
    if tokens.isupper() and len(tokens) > 4:
        return False  # КАПСЛОК (кроме аббревиатур)
    return True
✅ Checklist для нового парсера
 Наследуется от BaseParser

 fetch() использует fetch_with_retry + get_cached/save_cache

 extract_terms() возвращает list[str] (не set, порядок важен)

 Термины очищены (_clean_term или аналог)

 Дедупликация через _dedupe_ordered (case-insensitive)

 CLI с argparse: --url, --category, --output-dir, --no-cache

 Создана симуляция в tests/simulations/sim_{parser_name}.py

 Real test: 2–3 URL из url_audit.csv (разные типы страниц)

 Логирование: self.logger.info() на каждом этапе

 Документация: обновить CHANGELOG.md + этот файл

🧪 Симуляции
Для каждого парсера — симуляция в tests/simulations/:

python
# tests/simulations/sim_{parser_name}.py

def test_extract_terms():
    """Проверяет extract_terms() на реальных HTML-фрагментах."""
    html = """<table class="wikitable">..."""
    parser = WikiParser(url="...", category="1")
    terms = parser.extract_terms(html)
    assert "Жуков" in terms
    assert len(terms) >= 40

if __name__ == "__main__":
    test_extract_terms()
    print("✅ ALL GREEN")
Запуск:

bash
python tests/simulations/sim_wiki_parser.py
📊 Real Test Process
Выбрать 2–3 URL из url_audit.csv (разные типы страниц домена)

Запустить парсер:

bash
python scripts/vocab/parsers/my_parser.py --url "..." --category X
Проверить data/parsed/X/domain.txt:

Кол-во терминов соответствует ожиданиям

Нет мусора (цифры, служебные слова, HTML-теги)

Термины нормализованы (капитализация корректна)

Проверить логи: нет WARNING/ERROR

✅ GREEN → обновить docs → коммит

## 3. rkka_parser.py — rkka.ru (готов v17.23)

Двухуровневый crawler:

**Level 0 — directory page (oper.htm, hist/f.htm итд):**
- Текст ссылок → названия операций/статей (`_extract_level0_link_texts()`)
- Заголовки разделов из `<td>` без href (`_extract_table_cells()`)
- `_clean_link_text()`: фильтр кириллицы + стоп-слова начала строки (В, На, За...)
- Выход: ~50–80 терминов

**Level 1 — страницы операций (max 60 страниц):**
- 3 стратегии:
  1. `_extract_table_cells()`: scan `<td>` (командиры, формирования, данные)
  2. `_extract_rank_names()`: звание + ФИО (импорт из `militera_parser`)
  3. `_extract_unit_names()`: формирования всех падежей (импорт из `militera_parser`)
  4. `_extract_quoted_terms()`: текст в `«»` (импорт из `militera_parser`)
- Выход: ~20–50 терминов/страница

**Итого:** ~500–1500 терминов/директория

**Особенности:**
- Кодировка `windows-1251` явно (не autodetect — сайт 2000-х годов)
- `_is_content_link()`: фильтр `.htm/.html`, без внешних доменов / якорей / CSS/JS
- Дубли URL на index-странице снимаются через `seen` set в `_get_page_urls()`
- SSL: `verify=False` (через `utils.py`)
- Rate limit: 2 сек/запрос

**Real test результаты:**
- `http://rkka.ru/oper.htm` → 3486 терминов ✅
- Симуляция: `tests/simulations/sim_rkka_parser.py` (27/27 GREEN)

Версия: v17.23
Последнее обновление: 2026-03-06