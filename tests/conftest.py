#!/usr/bin/env python3
"""
tests/conftest.py - Настройка путей для pytest

🆕 v16.23: Добавляем scripts/ в sys.path для импорта модулей
"""

import sys
from pathlib import Path

# Добавляем scripts/ в Python path
project_root = Path(__file__).parent.parent
scripts_path = project_root / "scripts"
sys.path.insert(0, str(scripts_path))
