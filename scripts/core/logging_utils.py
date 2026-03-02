#!/usr/bin/env python3
"""
core/logging_utils.py — Утилиты логирования пайплайна
v17.19: Вынесено из transcribe.py (было встроено с v16.8–v17.10)

Содержит:
  - TeeOutput    — захват stdout в основной лог + фазовые логи
  - set_tee()    — регистрация активного экземпляра (вызывать в __main__)
  - switch_log_phase() — переключение фазового лог-файла
"""

import sys
from pathlib import Path


class TeeOutput:
    """
    Дублирует stdout в файл лога.

    Основной лог (_debug.log) пишется непрерывно.
    Дополнительно ведутся 4 фазовых лога в log/:
      01_diarization.log, 02_alignment.log, 03_merges.log, 04_postprocess.log
    """

    def __init__(self, main_log_path: Path):
        self.terminal = sys.stdout
        self.main_log = open(main_log_path, 'w', encoding='utf-8')
        self.phase_log = None
        self._phase_path = None

    def switch_phase(self, phase_path: Path):
        """Переключить фазовый файл; основной лог продолжает писаться."""
        if self.phase_log:
            self.phase_log.close()
        phase_path.parent.mkdir(parents=True, exist_ok=True)
        self.phase_log = open(phase_path, 'w', encoding='utf-8')
        self._phase_path = phase_path

    def write(self, message):
        self.terminal.write(message)
        self.main_log.write(message)
        if self.phase_log:
            self.phase_log.write(message)

    def flush(self):
        self.terminal.flush()
        self.main_log.flush()
        if self.phase_log:
            self.phase_log.flush()

    def close(self):
        if self.phase_log:
            self.phase_log.close()
        self.main_log.close()


# ─── Глобальный экземпляр (инициализируется из __main__) ─────────────────────

_tee: "TeeOutput | None" = None


def set_tee(tee_instance: TeeOutput):
    """Зарегистрировать активный TeeOutput. Вызывать в __main__ после создания."""
    global _tee
    _tee = tee_instance


def switch_log_phase(phase_path: Path):
    """
    Переключить фазовый лог-файл.
    Вызывать перед каждым этапом пайплайна из process_audio_file().
    """
    if _tee is not None:
        _tee.switch_phase(Path(phase_path))
