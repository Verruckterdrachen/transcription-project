#!/usr/bin/env python3
"""
make_bilingual_doc.py — Генератор билингвального Word-документа DE+RU

Формат вывода (Вариант B — таблица):
┌────────────┬──────────────────────────────┬──────────────────────────────┐
│ Таймкод    │ DE                           │ RU                           │
├────────────┼──────────────────────────────┼──────────────────────────────┤
│ 00:02:31   │ In seiner Rede...            │ —                            │
│ 00:03:01   │ Ankunft des...               │ Прибытие...                  │
│ 00:03:38   │ Vom Einsatz...               │ О боевом применении...       │
└────────────┴──────────────────────────────┴──────────────────────────────┘

Входные файлы:
  DE TXT: строки вида  "HH:MM:SS текст..."  (без метки спикера)
          или           "HH:MM:SS Диктор: текст..."  (метка удаляется автоматически)
  RU TXT: строки вида  "HH:MM:SS текст..."
          (внутренние таймкоды "HH:MM:SS" внутри строки тоже распознаются)

Алгоритм выравнивания:
  1. Парсим оба TXT → список блоков (timecode, text)
  2. Разбиваем длинные DE-блоки по внутренним таймкодам → суб-блоки
  3. Объединяем все таймкоды → единая хронологическая шкала
  4. Для каждого таймкода ищем ближайший DE и RU блок (tolerance=5s)
  5. Записываем в таблицу Word

Зависимости: pip install python-docx
"""

import re
import sys
from pathlib import Path
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement


# ═══════════════════════════════════════════════════════════════════════════
# КОНСТАНТЫ
# ═══════════════════════════════════════════════════════════════════════════

TS_RE = re.compile(r'\b(\d{2}:\d{2}:\d{2})\b')
SPEAKER_RE = re.compile(r'^(\d{2}:\d{2}:\d{2})\s+[^:]{1,30}:\s+', re.UNICODE)
LINE_RE    = re.compile(r'^(\d{2}:\d{2}:\d{2})\s+(.*)', re.DOTALL)

COL_WIDTHS_CM = [2.8, 7.6, 7.6]  # Таймкод | DE | RU

COLOR_HEADER_BG = "1F3864"   # тёмно-синий
COLOR_HEADER_FG = "FFFFFF"   # белый
COLOR_TS_BG     = "D9E1F2"   # светло-голубой
COLOR_DE_BG     = "FFFFFF"
COLOR_RU_BG     = "F2F2F2"   # чуть серый — визуальное разделение
COLOR_EMPTY     = "BFBFBF"   # серый для "—"

FONT_MAIN   = "Times New Roman"
FONT_TS     = "Courier New"
SIZE_HEADER = 11
SIZE_BODY   = 10
SIZE_TS     = 10

MATCH_TOLERANCE_SEC = 5  # секунд — допуск для сопоставления DE↔RU блоков


# ═══════════════════════════════════════════════════════════════════════════
# ПАРСИНГ TXT
# ═══════════════════════════════════════════════════════════════════════════

def ts_to_sec(ts: str) -> int:
    """'HH:MM:SS' → секунды (int)"""
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def parse_txt(path: Path) -> list[dict]:
    """
    Парсит TXT транскрипции → список блоков.

    Каждый блок: {'ts': 'HH:MM:SS', 'sec': int, 'text': str}

    Поддерживает форматы строк:
      "HH:MM:SS текст"
      "HH:MM:SS Диктор: текст"
      "HH:MM:SS Спикер: текст"

    Многострочные блоки (строки без таймкода в начале) присоединяются
    к последнему блоку.
    """
    blocks = []
    current = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Пропускаем разделители и footer-реестр [?]
        if line.startswith("=") or line.startswith("[?]") or line.startswith("⚠️"):
            continue

        m = LINE_RE.match(line)
        if m:
            ts   = m.group(1)
            text = m.group(2).strip()

            # Убираем метку спикера "Имя: " в начале текста
            spk = re.match(r'^[^:]{1,30}:\s+', text)
            if spk:
                text = text[spk.end():]

            if current:
                blocks.append(current)
            current = {"ts": ts, "sec": ts_to_sec(ts), "text": text}
        else:
            # Продолжение предыдущего блока
            if current:
                current["text"] += " " + line

    if current:
        blocks.append(current)

    return blocks


def split_by_inner_timestamps(blocks: list[dict]) -> list[dict]:
    """
    Разбивает блоки с внутренними таймкодами на суб-блоки.

    Пример: блок 00:02:31 с текстом "...Ankomstig. 00:03:01 Ankunft..."
    → два блока: 00:02:31 "...Ankomstig." и 00:03:01 "Ankunft..."
    """
    result = []
    for block in blocks:
        text  = block["text"]
        parts = TS_RE.split(text)

        if len(parts) == 1:
            # Нет внутренних таймкодов
            result.append(block)
            continue

        # parts = [pre_text, ts1, post1, ts2, post2, ...]
        # Первый фрагмент — до первого внутреннего таймкода
        pre_text = parts[0].strip()
        if pre_text:
            result.append({
                "ts":   block["ts"],
                "sec":  block["sec"],
                "text": pre_text
            })

        # Остальные — пары (таймкод, текст)
        i = 1
        while i < len(parts) - 1:
            inner_ts   = parts[i]
            inner_text = parts[i + 1].strip()
            if inner_text:
                result.append({
                    "ts":   inner_ts,
                    "sec":  ts_to_sec(inner_ts),
                    "text": inner_text
                })
            i += 2

    return result


# ═══════════════════════════════════════════════════════════════════════════
# ВЫРАВНИВАНИЕ DE ↔ RU
# ═══════════════════════════════════════════════════════════════════════════

def align_blocks(de_blocks: list[dict], ru_blocks: list[dict]) -> list[dict]:
    """
    Выравнивает DE и RU блоки по таймкодам → список строк таблицы.

    Каждая строка: {'ts': str, 'sec': int, 'de': str, 'ru': str}

    Алгоритм:
    1. Собираем все уникальные таймкоды из обоих списков
    2. Сортируем хронологически
    3. Для каждого таймкода находим лучшее совпадение в DE и RU
       (точное или ближайшее в пределах MATCH_TOLERANCE_SEC)
    4. Каждый блок используется не более одного раза
    """
    # Индексируем RU по секундам для быстрого поиска
    ru_by_sec = {b["sec"]: b for b in ru_blocks}
    ru_used   = set()
    de_used   = set()

    # Собираем все таймкоды
    all_secs = sorted(set(
        [b["sec"] for b in de_blocks] +
        [b["sec"] for b in ru_blocks]
    ))

    rows = []

    de_by_sec = {b["sec"]: b for b in de_blocks}

    for sec in all_secs:
        # Ищем DE блок
        de_block = None
        if sec in de_by_sec and sec not in de_used:
            de_block = de_by_sec[sec]
        else:
            # Ищем ближайший неиспользованный DE
            for b in de_blocks:
                if b["sec"] not in de_used and abs(b["sec"] - sec) <= MATCH_TOLERANCE_SEC:
                    de_block = b
                    break

        # Ищем RU блок
        ru_block = None
        if sec in ru_by_sec and sec not in ru_used:
            ru_block = ru_by_sec[sec]
        else:
            for b in ru_blocks:
                if b["sec"] not in ru_used and abs(b["sec"] - sec) <= MATCH_TOLERANCE_SEC:
                    ru_block = b
                    break

        # Пропускаем если оба уже использованы или оба пусты
        if de_block is None and ru_block is None:
            continue

        # Определяем таймкод строки
        ts  = de_block["ts"] if de_block else ru_block["ts"]
        row = {
            "ts":  ts,
            "sec": sec,
            "de":  de_block["text"] if de_block else "",
            "ru":  ru_block["text"] if ru_block else "",
        }

        if de_block:
            de_used.add(de_block["sec"])
        if ru_block:
            ru_used.add(ru_block["sec"])

        rows.append(row)

    return rows


# ═══════════════════════════════════════════════════════════════════════════
# WORD HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _set_cell_bg(cell, hex_color: str):
    """Устанавливает цвет фона ячейки."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd  = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  hex_color)
    tcPr.append(shd)


def _set_col_width(cell, width_cm: float):
    """Устанавливает ширину колонки."""
    tc   = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcW  = OxmlElement("w:tcW")
    tcW.set(qn("w:w"),    str(int(width_cm * 567)))  # 567 twips/cm
    tcW.set(qn("w:type"), "dxa")
    tcPr.append(tcW)


def _add_paragraph(cell, text: str, font_name: str, font_size: int,
                   bold=False, color_hex: str = None,
                   align=WD_ALIGN_PARAGRAPH.LEFT):
    """Добавляет параграф в ячейку с нужным форматированием."""
    para = cell.paragraphs[0]
    para.alignment = align
    run = para.add_run(text)
    run.font.name      = font_name
    run.font.size      = Pt(font_size)
    run.font.bold      = bold
    if color_hex:
        r, g, b = int(color_hex[0:2], 16), int(color_hex[2:4], 16), int(color_hex[4:6], 16)
        run.font.color.rgb = RGBColor(r, g, b)
    return para


def _set_row_height(row, height_cm: float):
    tr     = row._tr
    trPr   = tr.get_or_add_trPr()
    trH    = OxmlElement("w:trHeight")
    trH.set(qn("w:val"),   str(int(height_cm * 567)))
    trH.set(qn("w:hRule"), "atLeast")
    trPr.append(trH)


# ═══════════════════════════════════════════════════════════════════════════
# ГЕНЕРАЦИЯ ДОКУМЕНТА
# ═══════════════════════════════════════════════════════════════════════════

def build_doc(rows: list[dict], doc_title: str) -> Document:
    """
    Строит Word документ из выровненных строк.
    """
    doc = Document()

    # Поля страницы — уже (больше места для таблицы)
    for section in doc.sections:
        section.top_margin    = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin   = Cm(1.5)
        section.right_margin  = Cm(1.5)

    # Заголовок документа
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_para.add_run(doc_title)
    title_run.font.name  = FONT_MAIN
    title_run.font.size  = Pt(14)
    title_run.font.bold  = True

    doc.add_paragraph()  # отступ

    # Таблица
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"

    # Ширины колонок
    for i, cell in enumerate(table.rows[0].cells):
        _set_col_width(cell, COL_WIDTHS_CM[i])

    # Заголовок таблицы
    hdr_cells = table.rows[0].cells
    hdr_data  = ["Таймкод", "🇩🇪  DE", "🇷🇺  RU"]

    for i, (cell, label) in enumerate(zip(hdr_cells, hdr_data)):
        _set_cell_bg(cell, COLOR_HEADER_BG)
        _add_paragraph(cell, label,
                       font_name=FONT_MAIN, font_size=SIZE_HEADER,
                       bold=True, color_hex=COLOR_HEADER_FG,
                       align=WD_ALIGN_PARAGRAPH.CENTER)
        _set_col_width(cell, COL_WIDTHS_CM[i])
    _set_row_height(table.rows[0], 0.8)

    # Строки данных
    for row in rows:
        tr_cells = table.add_row().cells

        # ── Таймкод ──
        _set_cell_bg(tr_cells[0], COLOR_TS_BG)
        _add_paragraph(tr_cells[0], row["ts"],
                       font_name=FONT_TS, font_size=SIZE_TS,
                       bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        _set_col_width(tr_cells[0], COL_WIDTHS_CM[0])

        # ── DE ──
        _set_cell_bg(tr_cells[1], COLOR_DE_BG)
        if row["de"]:
            _add_paragraph(tr_cells[1], row["de"],
                           font_name=FONT_MAIN, font_size=SIZE_BODY)
        else:
            _add_paragraph(tr_cells[1], "—",
                           font_name=FONT_MAIN, font_size=SIZE_BODY,
                           color_hex=COLOR_EMPTY,
                           align=WD_ALIGN_PARAGRAPH.CENTER)
        _set_col_width(tr_cells[1], COL_WIDTHS_CM[1])

        # ── RU ──
        _set_cell_bg(tr_cells[2], COLOR_RU_BG)
        if row["ru"]:
            _add_paragraph(tr_cells[2], row["ru"],
                           font_name=FONT_MAIN, font_size=SIZE_BODY)
        else:
            _add_paragraph(tr_cells[2], "—",
                           font_name=FONT_MAIN, font_size=SIZE_BODY,
                           color_hex=COLOR_EMPTY,
                           align=WD_ALIGN_PARAGRAPH.CENTER)
        _set_col_width(tr_cells[2], COL_WIDTHS_CM[2])

    return doc


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  make_bilingual_doc.py — DE+RU билингвальная таблица")
    print("=" * 60)

    # ── Входные файлы ──
    de_input = input("\n📂 Путь к DE TXT файлу: ").strip().replace('"', '')
    ru_input = input("📂 Путь к RU TXT файлу (Enter — пропустить): ").strip().replace('"', '')
    out_input = input("💾 Путь для сохранения DOCX (Enter — рядом с DE): ").strip().replace('"', '')

    de_path = Path(de_input)
    if not de_path.exists():
        print(f"❌ Файл не найден: {de_path}")
        sys.exit(1)

    ru_path = Path(ru_input) if ru_input else None
    if ru_path and not ru_path.exists():
        print(f"❌ Файл не найден: {ru_path}")
        sys.exit(1)

    if out_input:
        out_path = Path(out_input)
    else:
        out_path = de_path.parent / (de_path.stem + "_bilingual.docx")

    doc_title = de_path.stem.replace("_", " ")

    # ── Парсинг ──
    print(f"\n📖 Парсинг DE: {de_path.name}")
    de_blocks = parse_txt(de_path)
    de_blocks = split_by_inner_timestamps(de_blocks)
    print(f"   → {len(de_blocks)} блоков после разбивки внутренних таймкодов")

    ru_blocks = []
    if ru_path:
        print(f"📖 Парсинг RU: {ru_path.name}")
        ru_blocks = parse_txt(ru_path)
        ru_blocks = split_by_inner_timestamps(ru_blocks)
        print(f"   → {len(ru_blocks)} блоков")
    else:
        print("ℹ️  RU файл не указан — колонка RU будет пустой (заготовка)")

    # ── Выравнивание ──
    print(f"\n🔗 Выравнивание DE↔RU (tolerance={MATCH_TOLERANCE_SEC}s)...")
    rows = align_blocks(de_blocks, ru_blocks)
    print(f"   → {len(rows)} строк в таблице")

    # ── Превью ──
    print(f"\n📋 Превью первых 5 строк:")
    for row in rows[:5]:
        de_preview = (row["de"][:50] + "...") if len(row["de"]) > 50 else row["de"] or "—"
        ru_preview = (row["ru"][:50] + "...") if len(row["ru"]) > 50 else row["ru"] or "—"
        print(f"   {row['ts']} | DE: {de_preview}")
        print(f"           | RU: {ru_preview}")
        print()

    # ── Генерация документа ──
    print(f"📝 Генерация DOCX...")
    doc = build_doc(rows, doc_title)
    doc.save(str(out_path))

    print(f"\n✅ Готово! Документ сохранён:")
    print(f"   {out_path}")
    print(f"   Строк в таблице: {len(rows)}")


if __name__ == "__main__":
    main()
