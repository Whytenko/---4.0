"""
Пакетная проверка: классификация файлов пакета (заявка / акт на простой /
акт-наряд), парсинг актов, сверка с заявками, сборка сводного Excel-отчёта.

Раньше эта логика жила прямо внутри API-класса interface.py — вынесена
сюда, чтобы быть доступной не только из GUI (например из консоли main.py
или отдельного скрипта), и чтобы её можно было протестировать отдельно от
pywebview.
"""
from __future__ import annotations

import io
import traceback
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class BatchResult:
    akt_paths: List[Path] = field(default_factory=list)
    wells_data: list = field(default_factory=list)
    zayavki: list = field(default_factory=list)
    prostoy_files: List[str] = field(default_factory=list)
    report_path: Optional[Path] = None
    stdout_text: str = ""
    stderr_text: str = ""
    # (имя файла, тип, причина) для каждого файла пакета — аудиторский след
    # классификации, чтобы будущее ложное срабатывание было видно в обычном
    # выводе, а не требовало отдельного debug-скрипта.
    classifications: List[tuple] = field(default_factory=list)


def run_batch_pipeline(pdf_paths: List[Path], progress_callback=None) -> BatchResult:
    """Классифицирует файлы пакета, парсит акты, сверяет с заявками и
    собирает сводный Excel-отчёт. Не поднимает исключения наружу — любая
    ошибка попадает в result.stderr_text, как и раньше в interface.py.

    progress_callback(stage, current, total, filename), если задан,
    вызывается по ходу обработки — используется для индикатора прогресса
    в GUI. stage: "classify" | "parse" | "report"."""
    result = BatchResult()
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()

    def _notify(stage: str, current: int, total: int, filename: str = "") -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(stage, current, total, filename)
        except Exception:
            pass

    try:
        from src.extractors.main_parser import PDFProcessor
        from src.extractors.doc_linking import (
            classify_pdf_with_reason,
            parse_zayavka_text,
            apply_zayavka_checks,
        )
        from src.utils.batch_report import build_batch_report

        total_files = len(pdf_paths)
        # Разделяем пакет: заявки идут на сверку (не как отдельные акты),
        # акты на простой — пока только фиксируются (полноценная автосверка
        # с тех.дежурством не реализована), всё остальное обрабатывается
        # как акт-наряд, как и раньше.
        for idx, path in enumerate(pdf_paths, start=1):
            _notify("classify", idx, total_files, path.name)
            kind, reason, text = classify_pdf_with_reason(path)
            result.classifications.append((path.name, kind, reason))
            if kind == "zayavka":
                record = parse_zayavka_text(text)
                record["filename"] = path.name
                result.zayavki.append(record)
            elif kind == "akt_prostoy":
                result.prostoy_files.append(path.name)
            else:
                result.akt_paths.append(path)

        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            print("Классификация пакета:")
            for filename, kind, reason in result.classifications:
                print(f"  [{kind}] {filename} — {reason}")

        processor = PDFProcessor()

        def _parse_progress(current: int, total: int, filename: str) -> None:
            _notify("parse", current, total, filename)

        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            result.wells_data = processor.process_pdfs(result.akt_paths, progress_callback=_parse_progress)
            if result.zayavki:
                apply_zayavka_checks(result.wells_data, result.zayavki)
            processor.print_all_results()
        _notify("report", len(result.akt_paths), len(result.akt_paths), "")
        if result.akt_paths:
            result.report_path = build_batch_report(result.akt_paths, result.wells_data)
    except Exception:
        traceback.print_exc(file=stderr_buffer)

    result.stdout_text = stdout_buffer.getvalue()
    result.stderr_text = stderr_buffer.getvalue()
    return result
