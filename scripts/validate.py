#!/usr/bin/env python3
"""
scripts/validate.py — Автоматизация VALIDATION.md (пункты 1, 2, 3, 5, 7)

Пункты 4, 6, 8 — только вручную (см. VALIDATION.md).

Usage:
		python scripts/validate.py                            # автопоиск в test-results/latest/
		python scripts/validate.py path/to/file.json
		python scripts/validate.py path/to/file.json path/to/file.txt
"""

import sys
import json
import re
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
# ПРОВЕРКИ
# ═══════════════════════════════════════════════════════════════════════════

def check_long_blocks(segments: list) -> list:
		"""
		Пункт 1: Блоки >30 сек без промежуточного timestamp в тексте.
		Если в seg['text'] есть HH:MM:SS — считаем, что блок разбит.
		"""
		issues = []
		ts_pattern = re.compile(r'\b\d{2}:\d{2}:\d{2}\b')

		for seg in segments:
				text     = seg.get('text', '')
				duration = seg.get('end', 0) - seg.get('start', 0)
				ts_count = len(ts_pattern.findall(text))

				if duration > 60 and ts_count == 0:
						issues.append(
								f"❌ [{seg.get('time','?')}] {duration:.1f}s — нет timestamp (>60s)"
						)
				elif duration > 30 and ts_count == 0:
						issues.append(
								f"⚠️ [{seg.get('time','?')}] {duration:.1f}s — нет timestamp (>30s)"
						)
		return issues


def check_duplicates(txt: str) -> list:
		"""
		Пункт 2: Повторяющиеся фразы (одна фраза дважды подряд).
		Ищем паттерн (.{20,})[.!?] ... \1
		"""
		issues = []
		# Ищем повторы через точку/восклицание/вопрос
		pattern = re.compile(r'(.{20,})[.!?]\s+\1', re.DOTALL)
		for m in pattern.finditer(txt):
				preview = m.group(1)[:60].replace('\n', ' ')
				issues.append(f"❌ Дубль: \"{preview}...\"")
		return issues


def check_stuttering(txt: str) -> list:
		"""
		Пункт 3: Незамаскированные заикания (слово повторяется без «...»).
		"""
		issues = []
		patterns = [
				(re.compile(r'\b(\w{3,})\s+\1\b', re.I), 'двойной повтор'),
				(re.compile(r'\b(\w{3,})\s+\1\s+\1\b', re.I), 'тройной повтор'),
		]
		seen = set()
		for pattern, label in patterns:
				for m in pattern.finditer(txt):
						# Проверяем: нет «...» рядом → настоящее заикание без маскировки
						start = max(0, m.start() - 5)
						context = txt[start: m.end() + 5]
						if '...' not in context and m.group() not in seen:
								seen.add(m.group())
								issues.append(f"⚠️ {label}: \"{m.group()}\"")
		return issues[:10]  # не спамить


def check_adjacent_speakers(segments: list) -> list:
		"""
		Пункт 5: Две реплики одного спикера подряд (должны быть смержены).
		"""
		issues = []
		for i in range(len(segments) - 1):
				s1 = segments[i].get('speaker', '')
				s2 = segments[i + 1].get('speaker', '')
				if s1 and s2 and s1 == s2:
						t1 = segments[i].get('time', '?')
						t2 = segments[i + 1].get('time', '?')
						issues.append(f"❌ {s1}: [{t1}] и [{t2}] — подряд")
		return issues


def check_gaps(segments: list, threshold: float = 3.0) -> list:
		"""
		Пункт 7: Необъяснённые гапы >3 сек между сегментами.
		"""
		issues = []
		for i in range(len(segments) - 1):
				gap = segments[i + 1].get('start', 0) - segments[i].get('end', 0)
				if gap > threshold:
						t1 = segments[i].get('time', '?')
						t2 = segments[i + 1].get('time', '?')
						issues.append(f"⚠️ GAP {t1} → {t2}: {gap:.1f}s")
		return issues


# ═══════════════════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_validation(json_path: Path, txt_path: Path | None = None) -> bool:
		"""
		Запустить все доступные автоматические проверки.
		Возвращает True если нет RED (только GREEN / MANUAL).
		"""
		print(f"\n{'═' * 60}")
		print(f"🔍 VALIDATION: {json_path.name}")
		if txt_path:
				print(f"   TXT: {txt_path.name}")
		print(f"{'═' * 60}")

		# ── Загрузка ────────────────────────────────────────────────────────
		with open(json_path, encoding='utf-8') as f:
				data = json.load(f)

		# JSON содержит segments_raw и segments_merged — валидируем финальный результат
		segments = data.get('segments_merged', [])
		if not segments:
				# Фоллбэк на segments_raw, если merged отсутствует (старые форматы)
				segments = data.get('segments_raw', [])
		if not segments:
				print("❌ Ключи 'segments_merged' и 'segments_raw' не найдены в JSON!")
				print(f"   Доступные ключи: {list(data.keys())}")
				return False

		print(f"   ✅ Загружено сегментов (merged): {len(segments)}")

		txt_content = ""
		if txt_path and txt_path.exists():
				txt_content = txt_path.read_text(encoding='utf-8')
		elif txt_path:
				print(f"⚠️ TXT не найден: {txt_path} — пропускаю текстовые проверки")

		# ── Проверки ─────────────────────────────────────────────────────────
		results = {}

		issues_1 = check_long_blocks(segments)
		results[1] = ("✅ GREEN", []) if not issues_1 else ("❌ RED", issues_1)

		if txt_content:
				issues_2 = check_duplicates(txt_content)
				results[2] = ("✅ GREEN", []) if not issues_2 else ("❌ RED", issues_2)

				issues_3 = check_stuttering(txt_content)
				results[3] = ("✅ GREEN", []) if not issues_3 else ("⚠️ CHECK", issues_3)
		else:
				results[2] = ("⚠️ SKIP", ["нет TXT — передай path/to/file.txt вторым аргументом"])
				results[3] = ("⚠️ SKIP", ["нет TXT"])

		results[4] = ("✋ MANUAL", [
				"grep -i 'продолжение следует\\|спасибо за внимание\\|подписывайтесь' *.txt"
		])

		issues_5 = check_adjacent_speakers(segments)
		results[5] = ("✅ GREEN", []) if not issues_5 else ("❌ RED", issues_5)

		results[6] = ("✋ MANUAL", [
				"Audacity: выбери 3–5 случайных timestamp из TXT, проверь совпадение"
		])

		issues_7 = check_gaps(segments)
		results[7] = ("✅ GREEN", []) if not issues_7 else ("⚠️ CHECK", issues_7)

		results[8] = ("✋ MANUAL", [
				"diff test-results/latest/ golden-dataset/<спикер>/"
		])

		# ── Вывод ─────────────────────────────────────────────────────────────
		LABELS = {
				1: "Длинные блоки",
				2: "Дубли",
				3: "Заикания",
				4: "Ending halluc.",
				5: "Смежные реплики",
				6: "Timestamp drift",
				7: "Гапы >3s",
				8: "Regression",
		}

		print("\n📋 VALIDATION CHECKLIST")
		print("━" * 55)
		has_red = False

		for n in range(1, 9):
				status, issues = results[n]
				check = "X" if "GREEN" in status else " "
				print(f"[{check}] {n}. {LABELS[n]:<22} {status}")
				if issues:
						for issue in issues[:3]:
								print(f"      {issue}")
						if len(issues) > 3:
								print(f"      ... и ещё {len(issues) - 3}")
				if "RED" in status:
						has_red = True

		print("━" * 55)
		pipeline_ver = data.get('pipeline_version', '?')
		print(f"Pipeline version в JSON: {pipeline_ver}")

		if not has_red:
				print("\n✅ Автоматические проверки — ВСЕ GREEN")
				print("✋ Проверь вручную пункты 4, 6, 8 — затем можно коммитить")
		else:
				print("\n❌ Есть RED — исправь перед коммитом!")

		return not has_red


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
		if len(sys.argv) >= 2:
				json_path = Path(sys.argv[1])
				txt_path  = Path(sys.argv[2]) if len(sys.argv) >= 3 else None
		else:
				# Автопоиск в test-results/latest/
				latest = Path(__file__).parent.parent / "test-results" / "latest"
				if not latest.exists():
						print("❌ Папка test-results/latest/ не найдена.")
						print("   Укажи путь явно: python scripts/validate.py path/to/file.json")
						sys.exit(1)

				jsons = sorted(latest.glob("*.json"))
				txts  = sorted(latest.glob("*.txt"))

				if not jsons:
						print(f"❌ JSON не найден в {latest}")
						print("   Сначала запусти: python scripts/transcribe.py")
						sys.exit(1)

				json_path = jsons[0]
				txt_path  = txts[0] if txts else None
				print(f"🔍 Автопоиск: {json_path.name}"
							+ (f" + {txt_path.name}" if txt_path else " (без TXT)"))

		if not json_path.exists():
				print(f"❌ Файл не найден: {json_path}")
				sys.exit(1)

		ok = run_validation(json_path, txt_path)
		sys.exit(0 if ok else 1)
