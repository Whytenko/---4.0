# config/paths.py

"""
Настройки путей к данным.
"""
import os
from pathlib import Path

# Путь к корню проекта
PROJECT_ROOT = Path(__file__).parent.parent

# Пути к папкам
DATA_DIR = PROJECT_ROOT / "data"
INPUT_PDFS_DIR = DATA_DIR / "input"
REFERENCE_DIR = DATA_DIR / "reference"
OUTPUT_DIR = DATA_DIR / "output"

# Создаем папки если не существуют
def create_directories():
    for directory in [INPUT_PDFS_DIR, REFERENCE_DIR, OUTPUT_DIR]:
        directory.mkdir(parents=True, exist_ok=True)

create_directories()

