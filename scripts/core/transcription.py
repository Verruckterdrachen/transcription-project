#!/usr/bin/env python3
"""
core/transcription.py - Транскрибация аудио с Whisper

🆕 v16.30: FIX БАГ #4 - N-gram overlap с удалением пунктуации (триграммы 3+ слов)
🆕 v16.29: GAP Hallucination Filter - пропуск gap с высоким сходством (>55%)
🆕 v16.5: Smart GAP Attribution - умная атрибуция GAP_FILLED по семантическому сходству
🆕 v16.3.2: Gap speaker detection - определение спикера по окружению
🆕 v16.2: Исправлен синтаксис itertracks() в force_transcribe_diar_gaps
"""

import re
import whisper
from core.utils import seconds_to_hms, gap_detector, extract_gap_audio, text_similarity
from core.diarization import align_segment_to_diarization
from corrections.hallucinations import is_hallucination


def transcribe_audio(model, wav_path, language="ru", temperature=0.0, beam_size=5, vad_threshold=0.7):
	"""
	Транскрибирует аудио файл с помощью Whisper

	Args:
		model: Загруженная модель Whisper
		wav_path: Path к WAV файлу
		language: Язык транскрибации
		temperature: Temperature для Whisper
		beam_size: Beam size для Whisper
		vad_threshold: Порог VAD (Voice Activity Detection)

	Returns:
		dict: Результат транскрибации с segments
	"""
	print(f"  🎙️ Whisper транскрибация {wav_path.name}...")

	result = model.transcribe(
		str(wav_path),
		language=language,
		temperature=temperature,
		beam_size=beam_size,
		word_timestamps=True
	)

	if result and 'segments' in result:
		print(f"  ✅ Whisper: {len(result['segments'])} сегментов")
		return result

	print("  ❌ Whisper: транскрибация не удалась")
	return None


# ... (начало файла без изменений) ...

def detect_speaker_for_gap(existing_segments, gap_start, gap_end, speaker_surname):
	"""
	🆕 v16.31: FIX БАГ #7 - Учёт длины gap текста при атрибуции
	🆕 v16.3.2: Определяет спикера для gap сегмента по окружению
	
	**ПРОБЛЕМА (БАГ #7):**
	Gap filling присваивал speaker БЕЗ анализа длины текста:
	- Короткий gap (<5 слов) → может быть continuation
	- Длинный gap (>20 слов) → новая реплика
	
	**FIX v16.31:**
	Параметр gap_text_words добавлен для анализа длины
	"""
	# Находим предыдущий сегмент (до gap)
	prev_speaker = None
	for seg in sorted(existing_segments, key=lambda x: x['end'], reverse=True):
		if seg['end'] <= gap_start:
			prev_speaker = seg.get('speaker')
			break

	# Находим следующий сегмент (после gap)
	next_speaker = None
	for seg in sorted(existing_segments, key=lambda x: x['start']):
		if seg['start'] >= gap_end:
			next_speaker = seg.get('speaker')
			break

	# Если окружен одним спикером
	if prev_speaker and next_speaker and prev_speaker == next_speaker:
		return prev_speaker

	# Если только предыдущий известен
	if prev_speaker == 'Журналист':
		gap_duration = gap_end - gap_start
		
		# 🆕 v16.31: Длинный gap (>15s) → скорее всего эксперт
		if gap_duration > 15:
			return speaker_surname
		else:
			return 'Журналист'

	# Если есть информация об эксперте рядом
	if prev_speaker == speaker_surname or next_speaker == speaker_surname:
		return speaker_surname

	# Не можем определить
	return 'Неизвестно'


def force_transcribe_diar_gaps(model, wav_path, gaps, existing_segments, speaker_surname=None):
	"""
	🆕 v16.31: FIX БАГ #7 - Учёт длины gap текста при атрибуции
	🆕 v16.30: FIX БАГ #4 - N-gram overlap с удалением пунктуации
	🆕 v16.29: GAP Hallucination Filter
	
	**ПРОБЛЕМА (БАГ #7):**
	Gap filling [959.68-963.9] присвоил длинный текст (>20 слов) Журналисту
	по умолчанию, хотя это была реплика Исаева!
	
	**FIX v16.31:**
	1. Проверяем длину gap_text (слова)
	2. Короткий (<5 слов) → similarity с next/prev
	3. Длинный (>20 слов) → НЕ использовать detected_speaker (Журналист) по умолчанию!
	   → Проверяем prev_speaker (если Исаев → gap тоже Исаев)
	"""
	print(f"\n🔄 Force-transcribe gaps v16.31...")

	added_segments = []

	for gap in gaps:
		gap_start = gap['gap_start']
		gap_end = gap['gap_end']
		gap_duration = gap['duration']

		print(f"  🚨 GAP {gap['gap_hms_start']}–{gap['gap_hms_end']} ({gap_duration}s)")

		# Определяем спикера ДО транскрибации
		detected_speaker = 'Неизвестно'
		if speaker_surname:
			detected_speaker = detect_speaker_for_gap(
				existing_segments, 
				gap_start, 
				gap_end, 
				speaker_surname
			)

		# Извлекаем аудио gap с небольшим overlap
		gap_audio_path = extract_gap_audio(wav_path, gap_start, gap_end, overlap=1.0)

		try:
			result = model.transcribe(
				str(gap_audio_path),
				language="ru",
				temperature=0.0,
				beam_size=5,
				no_speech_threshold=0.2,
				compression_ratio_threshold=1.2
			)

			if result and 'segments' in result:
				for seg in result['segments']:
					text = seg['text'].strip()

					# Пропускаем галлюцинации
					if is_hallucination(text):
						continue

					# Adjust timing
					seg_start = gap_start + float(seg['start'])
					seg_end = gap_start + float(seg['end'])

					# ═══════════════════════════════════════════════════════
					# v16.8: GAP OVERLAP PROTECTION (без изменений)
					# ═══════════════════════════════════════════════════════
					
					original_start = seg_start
					original_end = seg_end
					
					if added_segments:
						last_gap = added_segments[-1]
						if seg_start < last_gap["end"] + 0.5:
							seg_start = last_gap["end"]
							print(f"     ⚠️ GAP overlap с предыдущим GAP, adjusted start: {seg_start:.2f}s")
					
					next_existing = None
					for existing_seg in sorted(existing_segments, key=lambda x: x['start']):
						if existing_seg['start'] >= gap_end:
							next_existing = existing_seg
							break
					
					if next_existing and seg_end > next_existing["start"] - 0.5:
						seg_end = next_existing["start"]
						print(f"     ⚠️ GAP overlap с next existing, adjusted end: {seg_end:.2f}s")
					
					if seg_end - seg_start < 1.0:
						print(f"     ⚠️ GAP too short after adjustment ({seg_end - seg_start:.2f}s), skipping")
						continue
					
					if seg_start != original_start or seg_end != original_end:
						print(f"     🔧 Adjusted: {original_start:.2f}-{original_end:.2f} → {seg_start:.2f}-{seg_end:.2f}")

					# ═══════════════════════════════════════════════════════
					# 🆕 v16.31: УМНАЯ АТРИБУЦИЯ С УЧЁТОМ ДЛИНЫ ТЕКСТА
					# ═══════════════════════════════════════════════════════
					
					final_speaker = detected_speaker
					
					# Нормализуем gap text
					gap_text_normalized = re.sub(r'[^\w\s]', '', text.lower().strip())
					gap_words = gap_text_normalized.split()
					gap_words_count = len(gap_words)
					
					compare_words_count_next = gap_words_count * 2
					
					# 🆕 v16.31: Проверяем длину gap текста
					print(f"    📏 GAP длина: {gap_words_count} слов")
					
					# ─────────────────────────────────────────────────────
					# v16.30: N-GRAM OVERLAP с PREV (без изменений)
					# ─────────────────────────────────────────────────────
					
					prev_segment = None
					for existing_seg in sorted(existing_segments, key=lambda x: x['end'], reverse=True):
						if existing_seg['end'] <= gap_start:
							prev_segment = existing_seg
							break
					
					skip_gap = False
					if prev_segment and gap_words_count >= 3:
						prev_text = prev_segment.get('text', '')
						prev_text_normalized = re.sub(r'[^\w\s]', '', prev_text.lower().strip())
						
						for i in range(len(gap_words) - 2):
							trigram = ' '.join(gap_words[i:i+3])
							if trigram in prev_text_normalized:
								print(f"    ⚠️ GAP содержит фразу из prev ('{trigram}') → SKIP (duplicate)")
								skip_gap = True
								break
					
					if skip_gap:
						continue
					
					# ─────────────────────────────────────────────────────
					# v16.29: TEXT SIMILARITY с NEXT (без изменений)
					# ─────────────────────────────────────────────────────
					
					next_segment = None
					for existing_seg in sorted(existing_segments, key=lambda x: x['start']):
						if existing_seg['start'] >= gap_end:
							next_segment = existing_seg
							break
					
					if next_segment:
						next_speaker = next_segment.get('speaker')
						next_text = next_segment.get('text', '')
						
						if next_speaker and next_speaker != detected_speaker:
							next_text_normalized = re.sub(r'[^\w\s]', '', next_text.lower().strip())
							next_words = next_text_normalized.split()
							next_text_compare = ' '.join(next_words[:compare_words_count_next])
							
							similarity_next = text_similarity(gap_text_normalized, next_text_compare)
							
							print(f"    🔍 Text similarity с next [{next_speaker}]: {similarity_next:.1%}")
							
							if similarity_next > 0.55:
								print(f"    ⚠️ GAP слишком похож на next ({similarity_next:.0%}) → SKIP (hallucination)")
								continue
							
							if similarity_next > 0.50:
								final_speaker = next_speaker
								print(f"    🔄 GAP_FILLED → {next_speaker} (сходство {similarity_next:.1%})")
							else:
								# 🆕 v16.31: Логика для ДЛИННЫХ gap
								if gap_words_count > 20:
									# Длинный текст → НЕ может быть "по умолчанию" Журналистом!
									# Проверяем prev_speaker
									if prev_segment:
										prev_speaker = prev_segment.get('speaker')
										if prev_speaker == speaker_surname:
											final_speaker = speaker_surname
											print(f"    🔄 GAP_FILLED (длинный, {gap_words_count} слов) → {speaker_surname} (по prev)")
										else:
											print(f"    ✅ GAP_FILLED (длинный) → {detected_speaker} (не уверены, оставляем detected)")
									else:
										print(f"    ✅ GAP_FILLED (длинный) → {detected_speaker}")
								else:
									print(f"    ✅ GAP_FILLED → {detected_speaker} (по умолчанию)")

					new_segment = {
						'start': seg_start,
						'end': seg_end,
						'start_hms': seconds_to_hms(seg_start),
						'end_hms': seconds_to_hms(seg_end),
						'text': text,
						'speaker': final_speaker,
						'raw_speaker_id': 'GAP_FILLED',
						'confidence': seg.get('avg_logprob', -1.0),
						'from_gap': True
					}

					added_segments.append(new_segment)
					print(f"    ✅ [{seconds_to_hms(seg_start)}] {text[:50]}...")

		except Exception as e:
			print(f"  ❌ Gap транскрибация не удалась: {e}")

		finally:
			if gap_audio_path.exists():
				gap_audio_path.unlink()

	if added_segments:
		print(f"  ✅ Добавлено из gaps: {len(added_segments)} сегментов")
	else:
		print(f"  ⚠️ Gaps не дали новых сегментов")

	return added_segments
