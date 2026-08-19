"""
Сверка полного пайплайна на реальных актах из get_input_dir(): снимает
статус каждой проверки по каждому файлу в JSON-снимок и на повторных
запусках печатает диф с прошлым снимком. Задача — за секунды увидеть,
изменило ли поведение приложения текущий рефакторинг, вместо ручного
сравнения больших текстовых логов.

Если папка input пуста (например на чужой машине без реальных актов) —
мягкий no-op с понятным сообщением, по аналогии с src/utils/smoke_test.py.

Реальные PDF-акты — это данные клиента, они лежат в рантайм-папке
(AppData), а не в репозитории, и здесь не упоминаются по путям, шитым в код.

Запуск: python interface.py --verify-real-input
    или: python tools/verify_real_input.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.app_paths import ensure_runtime_layout, get_input_dir, get_logs_dir

SNAPSHOT_FILE_NAME = "real_input_verification_snapshot.json"


def _snapshot_path() -> Path:
    return get_logs_dir() / SNAPSHOT_FILE_NAME


def build_snapshot() -> Dict[str, object]:
    ensure_runtime_layout(copy_reference=True)

    from src.extractors.main_parser import PDFProcessor
    from src.extractors.doc_linking import classify_pdf, parse_zayavka_text, apply_zayavka_checks
    from src.extractors import km_parser, table_parser

    input_dir = get_input_dir()
    pdf_paths = sorted(input_dir.glob("*.pdf"))
    if not pdf_paths:
        return {"files": {}, "warning": f"Нет PDF в {input_dir} — сверка пропущена."}

    akt_paths: List[Path] = []
    zayavki = []
    prostoy_files: List[str] = []
    for path in pdf_paths:
        kind, text = classify_pdf(path)
        if kind == "zayavka":
            record = parse_zayavka_text(text)
            record["filename"] = path.name
            zayavki.append(record)
        elif kind == "akt_prostoy":
            prostoy_files.append(path.name)
        else:
            akt_paths.append(path)

    processor = PDFProcessor()
    wells_data = processor.process_pdfs(akt_paths)
    if zayavki:
        apply_zayavka_checks(wells_data, zayavki)

    files: Dict[str, object] = {}
    for path, well_data in zip(akt_paths, wells_data):
        checks = well_data.get_check_summary()
        row = {"classification": "akt_naryad"}
        row.update({key: result.get("status") for key, result in checks.items()})

        try:
            row["km"] = km_parser.compute_km_report(path).get("status")
        except Exception:
            row["km"] = "error"

        try:
            row["temperature"] = table_parser.get_temperature_status(well_data).get("status")
        except Exception:
            row["temperature"] = "error"

        files[path.name] = row

    for name in prostoy_files:
        files[name] = {"classification": "akt_prostoy"}

    return {"files": files, "zayavok": len(zayavki), "prostoy": len(prostoy_files)}


def diff_snapshots(old_files: Dict[str, object], new_files: Dict[str, object]) -> List[str]:
    changes: List[str] = []
    for name in sorted(set(old_files) | set(new_files)):
        old_row = old_files.get(name)
        new_row = new_files.get(name)
        if old_row is None:
            changes.append(f"+ {name}: новый файл в снимке")
            continue
        if new_row is None:
            changes.append(f"- {name}: пропал из снимка")
            continue
        for key in sorted(set(old_row) | set(new_row)):
            old_v = old_row.get(key)
            new_v = new_row.get(key)
            if old_v != new_v:
                changes.append(f"~ {name}.{key}: {old_v!r} -> {new_v!r}")
    return changes


def run() -> int:
    snapshot = build_snapshot()
    files = snapshot.get("files") or {}
    if not files:
        print(snapshot.get("warning", "Нет данных для сверки."))
        return 0

    path = _snapshot_path()
    old_snapshot = None
    if path.exists():
        try:
            old_snapshot = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            old_snapshot = None

    exit_code = 0
    if old_snapshot is None:
        print(f"Базовый снимок ещё не существует — создаю ({len(files)} акт(ов)).")
    else:
        changes = diff_snapshots(old_snapshot.get("files") or {}, files)
        if changes:
            print(f"⚠️  ИЗМЕНЕНИЯ по сравнению с прошлым снимком ({len(changes)}):")
            for line in changes:
                print(f"  {line}")
            exit_code = 1
        else:
            print(f"✅ Без изменений по сравнению с прошлым снимком ({len(files)} акт(ов)).")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run())
