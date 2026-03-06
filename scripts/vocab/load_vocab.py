#!/usr/bin/env python3
"""
load_vocab.py — White-list фильтрация + частотный scoring

Этап 4A Vocab Module:
- Читает data/final_dicts/combined_all.txt (85,904 термина)
- Применяет white-list паттерны (имена, техника, топонимы, воинские части)
- Подсчитывает частоту → веса 1-5
- Сохраняет в data/hotwords/combined_vocab.txt

Формат выхода:
Жуков:5
Рокоссовский:4
Операция Багратион:3

Usage:
    python scripts/vocab/load_vocab.py

Output:
    data/hotwords/combined_vocab.txt (~70K-80K терминов)
"""

import re
import sys
from pathlib import Path
from collections import Counter

# Добавляем корень проекта в путь
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ═══════════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════════

INPUT_FILE = PROJECT_ROOT / "data" / "final_dicts" / "combined_all.txt"
OUTPUT_FILE = PROJECT_ROOT / "data" / "hotwords" / "combined_vocab.txt"
PARSED_DIR = PROJECT_ROOT / "data" / "parsed"

# Стоп-слова (расширенный список из clean_dicts.py)
STOPWORDS = {
    'я', 'ты', 'он', 'она', 'оно', 'мы', 'вы', 'они',
    'мой', 'твой', 'его', 'её', 'наш', 'ваш', 'их',
    'этот', 'тот', 'такой', 'весь', 'сам', 'самый',
    'и', 'а', 'но', 'да', 'или', 'либо', 'то', 'если', 'что', 'как',
    'чтобы', 'когда', 'пока', 'хотя', 'словно', 'будто',
    'в', 'на', 'с', 'к', 'по', 'из', 'о', 'у', 'от', 'до', 'за', 'над',
    'под', 'при', 'про', 'через', 'без', 'для', 'ради', 'между',
    'не', 'ни', 'бы', 'ли', 'же', 'ведь', 'вот', 'даже', 'лишь', 'только',
    'очень', 'здесь', 'там', 'так', 'где', 'куда', 'откуда', 'когда',
    'всегда', 'никогда', 'часто', 'редко', 'можно', 'нужно', 'надо'
}

# ═══════════════════════════════════════════════════════════════════
# WHITE-LIST ФИЛЬТРЫ (копия из simulation)
# ═══════════════════════════════════════════════════════════════════

def is_proper_noun_pattern(term):
    """Имена собственные: Title Case, 2+ слова с заглавными"""
    words = term.split()
    has_capital = any(w[0].isupper() for w in words if w and w[0].isalpha())
    if not has_capital:
        return False
    
    if words[0][0].isupper():
        return True
    
    if words[0][0].isdigit() and len(words) > 1 and words[1][0].isupper():
        return True
    
    return False

def is_military_rank_pattern(term):
    """Воинское звание + имя/фамилия"""
    ranks = [
        'маршал', 'генерал', 'полковник', 'подполковник', 'майор',
        'капитан', 'лейтенант', 'сержант', 'ефрейтор', 'рядовой',
        'командир', 'командующий', 'начальник'
    ]
    
    words = term.lower().split()
    if len(words) < 2:
        return False
    
    if words[0] in ranks and term.split()[1][0].isupper():
        return True
    
    return False

def is_military_unit_pattern(term):
    """
    Воинские части: номер + воинский термин
    
    Примеры:
    ✅ 86-я дивизия, 1-й фронт, 267-я бригада, 5-я армия
    """
    pattern = r'^\d+-[яйе]\s+(дивизия|бригада|полк|батальон|рота|взвод|армия|корпус|фронт|флот|эскадра)'
    return bool(re.match(pattern, term, re.IGNORECASE))

def is_technical_term(term):
    """Техника с цифрами и дефисами"""
    pattern = r'^[А-ЯЁ][а-яё]*-\d+$|^[A-Z][a-z]+-[A-Z][a-z]+-?\d*$'
    return bool(re.match(pattern, term))

def is_abbreviation(term):
    """Аббревиатуры: ≤4 символа, uppercase"""
    if len(term) > 4:
        return False
    
    if term.isupper() and term.isalpha():
        if term.lower() in STOPWORDS:
            return False
        return True
    
    return False

def is_toponym_pattern(term):
    """Топонимы с характерными окончаниями"""
    endings = [
        'град', 'бург', 'полье', 'ладожье', 'поволжье',
        'ский', 'ская', 'ское',
        'ино', 'ово', 'ево'
    ]
    
    if not term[0].isupper():
        return False
    
    term_lower = term.lower()
    return any(term_lower.endswith(end) for end in endings)

def contains_verb_in_middle(term):
    """Фильтр глаголов в середине фразы"""
    verb_patterns = [
        r'\b(был|были|была|было)\b',
        r'\b(начал|начала|начали|начало)\b',
        r'\b(стал|стала|стали|стало)\b',
        r'\b(мог|могла|могли|могло)\b',
        r'\b(имел|имела|имели|имело)\b'
    ]
    
    for pattern in verb_patterns:
        if re.search(pattern, term, re.IGNORECASE):
            return True
    
    return False

def is_sentence_fragment(term):
    """Фрагменты предложений (>5 слов или есть глаголы)"""
    words = term.split()
    
    if len(words) > 5:
        return True
    
    if contains_verb_in_middle(term):
        return True
    
    return False

def load_vocab_whitelist(terms):
    """White-list фильтрация терминов"""
    result = []
    stats = {
        'proper_noun': 0,
        'military_rank': 0,
        'military_unit': 0,
        'technical': 0,
        'abbreviation': 0,
        'toponym': 0,
        'rejected_sentence': 0,
        'rejected_verb': 0,
        'rejected_stopword': 0
    }
    
    for term in terms:
        term = term.strip()
        if not term:
            continue
        
        # Фильтр: стоп-слова
        if len(term.split()) == 1 and term.lower() in STOPWORDS:
            stats['rejected_stopword'] += 1
            continue
        
        # Фильтр: фрагменты предложений
        if is_sentence_fragment(term):
            stats['rejected_sentence'] += 1
            continue
        
        # Фильтр: глаголы в середине
        if contains_verb_in_middle(term):
            stats['rejected_verb'] += 1
            continue
        
        # White-list паттерны (порядок важен!)
        if is_military_unit_pattern(term):
            stats['military_unit'] += 1
            result.append(term)
        elif is_proper_noun_pattern(term):
            stats['proper_noun'] += 1
            result.append(term)
        elif is_military_rank_pattern(term):
            stats['military_rank'] += 1
            result.append(term)
        elif is_technical_term(term):
            stats['technical'] += 1
            result.append(term)
        elif is_abbreviation(term):
            stats['abbreviation'] += 1
            result.append(term)
        elif is_toponym_pattern(term):
            stats['toponym'] += 1
            result.append(term)
    
    return result, stats

def calculate_frequency_scores(terms, parsed_dir):
    """
    Подсчёт частоты терминов в корпусе data/parsed/
    
    Args:
        terms: список отфильтрованных терминов
        parsed_dir: Path к data/parsed/
    
    Returns:
        dict {term: weight}
    """
    print("\n📊 Подсчёт частоты в корпусе...")
    
    # Читаем все файлы из data/parsed/*/*.txt
    freq_counter = Counter()
    total_files = 0
    
    for txt_file in parsed_dir.rglob("*.txt"):
        try:
            with open(txt_file, 'r', encoding='utf-8') as f:
                content = f.read().lower()
                
                # Подсчитываем вхождения каждого термина
                for term in terms:
                    # Case-insensitive подсчёт
                    count = content.count(term.lower())
                    if count > 0:
                        freq_counter[term.lower()] += count
                
                total_files += 1
        except Exception as e:
            print(f"   ⚠️ Ошибка чтения {txt_file.name}: {e}")
    
    print(f"   Обработано файлов: {total_files}")
    print(f"   Терминов с частотой >0: {len(freq_counter)}")
    
    # Маппинг частоты → вес 1-5
    scores = {}
    max_freq = max(freq_counter.values()) if freq_counter else 1
    
    for term in terms:
        freq = freq_counter.get(term.lower(), 1)
        
        # Логарифмическая шкала
        if freq >= max_freq * 0.5:
            weight = 5
        elif freq >= max_freq * 0.2:
            weight = 4
        elif freq >= max_freq * 0.05:
            weight = 3
        elif freq >= max_freq * 0.01:
            weight = 2
        else:
            weight = 1
        
        scores[term] = weight
    
    return scores

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("load_vocab.py — White-list фильтрация + frequency scoring")
    print("=" * 70)
    
    # Проверка входного файла
    if not INPUT_FILE.exists():
        print(f"\n❌ Файл не найден: {INPUT_FILE}")
        print("   Запусти сначала: python scripts/vocab/clean_dicts.py")
        return 1
    
    # Чтение терминов
    print(f"\n📂 Чтение: {INPUT_FILE}")
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        terms = [line.strip() for line in f if line.strip()]
    
    print(f"   Входных терминов: {len(terms):,}")
    
    # White-list фильтрация
    print("\n🔍 White-list фильтрация...")
    filtered, stats = load_vocab_whitelist(terms)
    
    print(f"\n📊 Статистика фильтрации:")
    print(f"   Входных терминов:       {len(terms):,}")
    print(f"   После white-list:       {len(filtered):,}")
    print(f"   Proper nouns:           {stats['proper_noun']:,}")
    print(f"   Military ranks:         {stats['military_rank']:,}")
    print(f"   Military units:         {stats['military_unit']:,}")
    print(f"   Technical terms:        {stats['technical']:,}")
    print(f"   Abbreviations:          {stats['abbreviation']:,}")
    print(f"   Toponyms:               {stats['toponym']:,}")
    print(f"   Rejected (sentences):   {stats['rejected_sentence']:,}")
    print(f"   Rejected (verbs):       {stats['rejected_verb']:,}")
    print(f"   Rejected (stopwords):   {stats['rejected_stopword']:,}")
    
    reduction = (1 - len(filtered) / len(terms)) * 100
    print(f"   Сокращение:             {reduction:.1f}%")
    
    # Frequency scoring
    if PARSED_DIR.exists():
        scores = calculate_frequency_scores(filtered, PARSED_DIR)
    else:
        print(f"\n⚠️ Папка {PARSED_DIR} не найдена, все веса = 1")
        scores = {term: 1 for term in filtered}
    
    # Создание выходной папки
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # Сохранение
    print(f"\n💾 Сохранение: {OUTPUT_FILE}")
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for term in sorted(filtered):
            weight = scores.get(term, 1)
            f.write(f"{term}:{weight}\n")
    
    print(f"   Сохранено терминов: {len(filtered):,}")
    
    # Образцы
    print(f"\n📝 Образцы (первые 20):")
    for term in list(sorted(filtered))[:20]:
        weight = scores.get(term, 1)
        print(f"   {term}:{weight}")
    
    print("\n✅ Готово!")
    print(f"\n📂 Результат: {OUTPUT_FILE}")
    print(f"   Термин:вес — {len(filtered):,} строк")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
