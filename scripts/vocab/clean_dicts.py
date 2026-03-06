#!/usr/bin/env python3
"""
scripts/vocab/clean_dicts.py

Очистка и дедупликация сырого словаря (щадящий режим + фильтр родительного падежа).

Usage:
    python scripts/vocab/clean_dicts.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from utils import setup_logger

# ─────────────────────────────────────────────
# КОНСТАНТЫ
# ─────────────────────────────────────────────

INPUT_FILE = Path("data/raw_dicts/combined_all.txt")
OUTPUT_FILE = Path("data/final_dicts/combined_all.txt")

MIN_LENGTH = 3
MAX_LENGTH = 100

# ─────────────────────────────────────────────
# СТОП-СЛОВА (ТОЛЬКО ЯВНЫЙ МУСОР)
# ─────────────────────────────────────────────

# Местоимения и указательные слова
PRONOUNS = {
    "я", "ты", "он", "она", "оно", "мы", "вы", "они",
    "мой", "твой", "его", "её", "наш", "ваш", "их",
    "этот", "эта", "это", "эти",
    "тот", "та", "то", "те",
    "такой", "такая", "такое", "такие",
    "весь", "вся", "всё", "все",
    "каждый", "любой", "другой", "сам",
}

# Союзы и частицы
CONJUNCTIONS = {
    "и", "а", "но", "или", "да", "же", "ли", "не", "ни",
    "если", "чтобы", "когда", "как", "что", "где", "куда",
    "хотя", "пока", "также", "тоже", "либо", "однако",
    "тем", "чем", "нежели",
}

# Предлоги
PREPOSITIONS = {
    "в", "на", "по", "из", "от", "до", "для", "при", "через",
    "под", "над", "между", "перед", "после", "во", "со", "ко",
    "без", "у", "около", "вокруг", "против", "среди", "ради",
    "благодаря", "согласно", "вопреки", "несмотря",
}

# Наречия
ADVERBS = {
    "очень", "так", "еще", "уже", "только", "даже", "лишь",
    "почти", "совсем", "вполне", "едва", "чуть", "слишком",
    "более", "менее", "самый", "наиболее", "наименее",
    "потом", "затем", "тогда", "теперь", "сейчас", "снова",
    "опять", "вновь", "всегда", "никогда", "иногда", "часто",
}

# Wikipedia-шаблоны
WIKI_TEMPLATES = {
    "дата", "противники", "итог", "командующие", "силы сторон",
    "потери", "см. также", "см.", "также", "примечания", "источники",
    "ссылки", "литература", "комментарии", "содержание",
    "медиафайлы на викискладе", "медиафайлы", "викискладе",
    "основной конфликт", "ход операции", "итоги операции",
    "состав", "численность", "вооружение", "результат",
}

STOPWORDS = PRONOUNS | CONJUNCTIONS | PREPOSITIONS | ADVERBS | WIKI_TEMPLATES

# Префиксы предложений
SENTENCE_STARTERS = {
    "был", "была", "было", "были", "стал", "стала", "стали",
    "начал", "начала", "начались", "пошел", "пошла", "пошли",
    "мне", "мною", "меня", "тебе", "тобой", "тебя",
    "ему", "ей", "им", "нам", "вам",
    "только", "уже", "еще", "всё", "так", "теперь", "тогда",
    "одновременно", "немедленно", "внезапно",
}

# Паттерны для отклонения
PATTERNS_TO_REJECT = [
    re.compile(r"^\d+$"),
    re.compile(r"^[a-zA-Z\s]+$"),
    re.compile(r"[<>{}()\[\]]"),
    re.compile(r"https?://"),
    re.compile(r"^\W+$"),
    re.compile(
        r"\b(напомнил|приходилось|поинтересовался|улыбнулся|"
        r"пишут|писал|говорил|сказал|ответил|спросил|"
        r"видел|слышал|знал|думал|считал|полагал|"
        r"надеялось|продолжал|продолжали|оказывал|оказывали)\b",
        re.IGNORECASE
    ),
    re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}"),
]

# ─────────────────────────────────────────────
# ФУНКЦИИ
# ─────────────────────────────────────────────

def normalize_term(term: str) -> str:
    """Базовая нормализация."""
    term = term.strip()
    term = re.sub(r"\s+", " ", term)
    return term


def is_genitive_fragment(term: str) -> bool:
    """
    Проверяет, является ли строка фрагментом предложения
    с родительным падежом в начале.
    
    Примеры:
    - "Германии было важно" → True (REJECT)
    - "Германии актов" → True (REJECT)
    - "Германия" → False (OK, одно слово)
    - "Германский фронт" → False (OK, не родительный падеж)
    
    Args:
        term: проверяемая строка
        
    Returns:
        True, если это фрагмент с родительным падежом
    """
    words = term.split()
    
    # Одно слово — не фрагмент (может быть валидным топонимом)
    if len(words) == 1:
        return False
    
    first_word = words[0].lower()
    
    # Окончания родительного падежа
    genitive_endings = ("ии", "ий", "ия", "ей", "ов", "ев", "ам", "ям", "ах", "ях")
    
    if first_word.endswith(genitive_endings):
        # Исключения: известные страны/регионы в родительном падеже
        # могут быть частью валидного термина
        known_genitives = {
            "германии", "италии", "франции", "польши", "румынии",
            "венгрии", "австрии", "чехословакии", "югославии",
            "финляндии", "норвегии", "швеции", "испании",
        }
        
        # Если это известная страна в род. падеже + ещё слова
        # проверяем второе слово
        if first_word in known_genitives:
            # "Германии войска" — может быть валидным
            # "Германии было важно" — точно мусор (есть глагол)
            
            # Проверяем второе слово на глаголы
            if len(words) > 1:
                second_word = words[1].lower()
                # Типичные глаголы в прошедшем времени
                verb_markers = (
                    "был", "была", "было", "были", "стал", "начал",
                    "пошел", "имел", "мог", "должен", "может", "может",
                )
                if second_word in verb_markers:
                    return True  # REJECT
        else:
            # Неизвестное слово в род. падеже + другие слова = фрагмент
            return True
    
    return False


def is_valid_term(term: str) -> bool:
    """
    Проверяет валидность термина (щадящий режим + фильтр род. падежа).
    """
    # 1. Длина
    if len(term) < MIN_LENGTH or len(term) > MAX_LENGTH:
        return False
    
    # 2. Паттерны (HTML, URL, глаголы)
    for pattern in PATTERNS_TO_REJECT:
        if pattern.search(term):
            return False
    
    # 3. Стоп-слова (полное совпадение)
    if term.lower() in STOPWORDS:
        return False
    
    # 4. Префиксы предложений
    first_word = term.split()[0].lower()
    if first_word in SENTENCE_STARTERS:
        return False
    
    # 5. НОВОЕ: Фильтр родительного падежа
    if is_genitive_fragment(term):
        return False
    
    # 6. Слишком много слов (8+ = предложение)
    if len(term.split()) > 8:
        return False
    
    # 7. Строка состоит только из стоп-слов
    words = term.lower().split()
    if all(w in STOPWORDS for w in words):
        return False
    
    return True


def deduplicate_case_insensitive(terms: list[str]) -> list[str]:
    """
    Дедупликация с сохранением наилучшего варианта капитализации.
    """
    freq = Counter(t.lower() for t in terms)
    
    variants: dict[str, list[str]] = {}
    for term in terms:
        lower = term.lower()
        if lower not in variants:
            variants[lower] = []
        variants[lower].append(term)
    
    best_variant: dict[str, str] = {}
    
    for lower, term_list in variants.items():
        title_case = [t for t in term_list if t.istitle()]
        first_capital = [t for t in term_list if t[0].isupper()]
        
        if title_case:
            best_variant[lower] = title_case[0]
        elif first_capital:
            best_variant[lower] = first_capital[0]
        else:
            best_variant[lower] = term_list[0]
    
    result = sorted(
        best_variant.values(),
        key=lambda t: (-freq[t.lower()], t.lower())
    )
    
    return result


def clean_dictionary(input_path: Path, output_path: Path) -> dict[str, int]:
    """Читает, очищает, дедуплицирует, сохраняет."""
    logger = setup_logger(__name__)
    
    logger.info(f"Чтение: {input_path}")
    
    with open(input_path, "r", encoding="utf-8") as f:
        raw_terms = [line.rstrip() for line in f if line.strip()]
    
    stats = {
        "input": len(raw_terms),
        "after_filter": 0,
        "after_dedup": 0,
        "rejected": 0,
        "genitive_fragments": 0,  # НОВОЕ
    }
    
    logger.info(f"Загружено терминов: {stats['input']:,}")
    
    # Фильтрация
    logger.info("Фильтрация мусора...")
    
    valid_terms = []
    rejected_samples = []
    genitive_samples = []  # НОВОЕ: примеры фрагментов с род. падежом
    
    for term in raw_terms:
        normalized = normalize_term(term)
        
        # Проверка на род. падеж отдельно (для статистики)
        if is_genitive_fragment(normalized):
            stats["genitive_fragments"] += 1
            if len(genitive_samples) < 5:
                genitive_samples.append(normalized)
            stats["rejected"] += 1
            continue
        
        if is_valid_term(normalized):
            valid_terms.append(normalized)
        else:
            stats["rejected"] += 1
            if len(rejected_samples) < 10:
                rejected_samples.append(normalized)
    
    stats["after_filter"] = len(valid_terms)
    
    logger.info(f"После фильтрации: {stats['after_filter']:,}")
    logger.info(f"Отклонено (общее): {stats['rejected']:,}")
    logger.info(f"  из них род. падеж: {stats['genitive_fragments']:,}")
    
    if genitive_samples:
        logger.info(f"Примеры род. падежа: {genitive_samples}")
    if rejected_samples:
        logger.info(f"Примеры другого мусора: {rejected_samples[:5]}")
    
    # Дедупликация
    logger.info("Дедупликация (case-insensitive)...")
    unique_terms = deduplicate_case_insensitive(valid_terms)
    
    stats["after_dedup"] = len(unique_terms)
    
    # Сохранение
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        for term in unique_terms:
            f.write(f"{term}\n")
    
    logger.info(f"Сохранено в: {output_path}")
    
    return stats


def main() -> None:
    """Главная функция."""
    logger = setup_logger(__name__)
    
    logger.info("=" * 60)
    logger.info("ОЧИСТКА СЛОВАРЯ (ЩАДЯЩИЙ + ФИЛЬТР РОД. ПАДЕЖА)")
    logger.info("=" * 60)
    
    if not INPUT_FILE.exists():
        logger.error(f"❌ Не найден файл: {INPUT_FILE}")
        logger.error("Запустите: python scripts/vocab/build_raw_dicts.py")
        sys.exit(1)
    
    stats = clean_dictionary(INPUT_FILE, OUTPUT_FILE)
    
    # Статистика
    logger.info("=" * 60)
    logger.info("РЕЗУЛЬТАТ")
    logger.info("=" * 60)
    logger.info(f"Входных терминов:        {stats['input']:,}")
    logger.info(f"После фильтрации:        {stats['after_filter']:,}")
    logger.info(f"После дедупликации:      {stats['after_dedup']:,}")
    logger.info(f"Отклонено (общее):       {stats['rejected']:,}")
    logger.info(f"  - род. падеж:          {stats['genitive_fragments']:,}")
    logger.info(f"  - другое:              {stats['rejected'] - stats['genitive_fragments']:,}")
    logger.info(f"Дубликатов удалено:      {stats['after_filter'] - stats['after_dedup']:,}")
    logger.info(f"Итоговое сокращение:     {100 * (stats['input'] - stats['after_dedup']) / stats['input']:.1f}%")
    logger.info("=" * 60)
    
    logger.info("✅ Очистка завершена")
    logger.info("")
    logger.info("💡 Проверь качество:")
    logger.info(f"   head -100 {OUTPUT_FILE}")
    logger.info(f"   grep -i 'германии' {OUTPUT_FILE}")
    logger.info(f"   grep -i 'цитадель' {OUTPUT_FILE}")
    logger.info(f"   grep -i 'багратион' {OUTPUT_FILE}")
    logger.info("")
    logger.info("Следующий шаг: python scripts/vocab/load_vocab.py")


if __name__ == "__main__":
    main()
