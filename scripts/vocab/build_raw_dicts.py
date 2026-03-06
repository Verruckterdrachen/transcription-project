#!/usr/bin/env python3
"""
scripts/vocab/build_raw_dicts.py

Объединяет все файлы из data/parsed/*/*.txt в один сырой словарь.
Без дедупликации и очистки — это будет на следующем этапе (clean_dicts.py).

Usage:
    python scripts/vocab/build_raw_dicts.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

# Добавляем scripts/vocab в sys.path для импорта utils
sys.path.insert(0, str(Path(__file__).parent))

from utils import setup_logger

# ─────────────────────────────────────────────
# КОНСТАНТЫ
# ─────────────────────────────────────────────

PARSED_DIR = Path("data/parsed")
OUTPUT_DIR = Path("data/raw_dicts")
OUTPUT_FILE = OUTPUT_DIR / "combined_all.txt"

# ─────────────────────────────────────────────
# ОСНОВНАЯ ЛОГИКА
# ─────────────────────────────────────────────

def find_all_parsed_files() -> list[Path]:
    """
    Рекурсивно находит все .txt файлы в data/parsed/*/*.
    
    Returns:
        Список путей к файлам, отсортированный для детерминированности.
    """
    if not PARSED_DIR.exists():
        return []
    
    files = list(PARSED_DIR.rglob("*.txt"))
    return sorted(files)


def read_terms_from_file(file_path: Path) -> Iterator[str]:
    """
    Читает файл построчно, возвращает непустые строки.
    
    Args:
        file_path: путь к .txt файлу
        
    Yields:
        Строка (без trailing whitespace)
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip()
                if line:  # пропускаем пустые строки
                    yield line
    except Exception as e:
        # Логируем ошибку, но не останавливаем процесс
        logger = setup_logger(__name__)
        logger.warning(f"Не удалось прочитать {file_path}: {e}")


def merge_all_files(files: list[Path], output_path: Path) -> dict[str, int]:
    """
    Объединяет все файлы в один, считает статистику.
    
    Args:
        files: список файлов для объединения
        output_path: путь к выходному файлу
        
    Returns:
        Словарь со статистикой: {"total_files": N, "total_terms": M, "empty_files": K}
    """
    logger = setup_logger(__name__)
    
    # Создаём выходную директорию
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    stats = {
        "total_files": len(files),
        "total_terms": 0,
        "empty_files": 0,
    }
    
    with open(output_path, "w", encoding="utf-8") as out:
        for file_path in files:
            terms_from_file = 0
            
            for term in read_terms_from_file(file_path):
                out.write(f"{term}\n")
                terms_from_file += 1
                stats["total_terms"] += 1
            
            if terms_from_file == 0:
                stats["empty_files"] += 1
                logger.warning(f"Пустой файл: {file_path}")
            else:
                logger.info(f"✓ {file_path.relative_to(PARSED_DIR)}: {terms_from_file} терминов")
    
    return stats


def main() -> None:
    """Главная функция."""
    logger = setup_logger(__name__)
    
    logger.info("=" * 60)
    logger.info("ОБЪЕДИНЕНИЕ PARSED ФАЙЛОВ В СЫРОЙ СЛОВАРЬ")
    logger.info("=" * 60)
    
    # 1. Находим все файлы
    files = find_all_parsed_files()
    
    if not files:
        logger.error(f"❌ Не найдено .txt файлов в {PARSED_DIR}")
        logger.error("Запустите сначала: python scripts/vocab/run_all_parsers.py --all")
        sys.exit(1)
    
    logger.info(f"Найдено файлов: {len(files)}")
    
    # 2. Объединяем
    stats = merge_all_files(files, OUTPUT_FILE)
    
    # 3. Итоговая статистика
    logger.info("=" * 60)
    logger.info("РЕЗУЛЬТАТ")
    logger.info("=" * 60)
    logger.info(f"Обработано файлов:  {stats['total_files']}")
    logger.info(f"Пустых файлов:      {stats['empty_files']}")
    logger.info(f"Всего терминов:     {stats['total_terms']}")
    logger.info(f"Выходной файл:      {OUTPUT_FILE}")
    logger.info("=" * 60)
    
    if stats["empty_files"] > 0:
        logger.warning(
            f"⚠️  Обнаружено {stats['empty_files']} пустых файлов — "
            "проверьте логи парсеров"
        )
    
    logger.info("✅ Объединение завершено")
    logger.info("Следующий шаг: python scripts/vocab/clean_dicts.py")


if __name__ == "__main__":
    main()
