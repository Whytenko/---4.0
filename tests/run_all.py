"""
Простой раннер регрессионных тестов — без pytest (в проекте он не
используется). Находит все test_*.py в этой папке, вызывает все функции
test_*() внутри них, печатает pass/fail по каждой.

Запуск: python tests/run_all.py
"""
from __future__ import annotations

import importlib
import inspect
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
for p in (PROJECT_ROOT, TESTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def discover_test_modules() -> list[str]:
    return sorted(p.stem for p in TESTS_DIR.glob("test_*.py"))


def run() -> int:
    total = 0
    failed = 0
    for module_name in discover_test_modules():
        module = importlib.import_module(module_name)
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("test_") or fn.__module__ != module_name:
                continue
            total += 1
            try:
                fn()
                print(f"  OK    {module_name}.{name}")
            except Exception:
                failed += 1
                print(f"  FAIL  {module_name}.{name}")
                traceback.print_exc()

    print()
    status = "ВСЕ ПРОШЛИ" if failed == 0 else f"ПРОВАЛЕНО: {failed}"
    print(f"Итого проверок: {total}. {status}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
