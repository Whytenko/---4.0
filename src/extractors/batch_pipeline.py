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


def run_batch_pipeline(pdf_paths: List[Path]) -> BatchResult:
    """Классифицирует файлы пакета, парсит акты, сверяет с заявками и
    собирает сводный Excel-отчёт. Не поднимает исключения наружу — любая
    ошибка попадает в result.stderr_text, как и раньше в interface.py."""
    result = BatchResult()
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()

    try:
        from src.extractors.main_parser import PDFProcessor
        from src.extractors.doc_linking import (
            classify_pdf,
            parse_zayavka_text,
            apply_zayavka_checks,
        )
        from src.utils.batch_report import build_batch_report

        # Разделяем пакет: заявки идут на сверку (не как отдельные акты),
        # акты на простой — пока только фиксируются (полноценная автосверка
        # с тех.дежурством не реализована), всё остальное обрабатывается
        # как акт-наряд, как и раньше.
        for path in pdf_paths:
            kind, text = classify_pdf(path)
            if kind == "zayavka":
                record = parse_zayavka_text(text)
                record["filename"] = path.name
                result.zayavki.append(record)
            elif kind == "akt_prostoy":
                result.prostoy_files.append(path.name)
            else:
                result.akt_paths.append(path)

        processor = PDFProcessor()
        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            result.wells_data = processor.process_pdfs(result.akt_paths)
            if result.zayavki:
                apply_zayavka_checks(result.wells_data, result.zayavki)
            processor.print_all_results()
        if result.akt_paths:
            result.report_path = build_batch_report(result.akt_paths, result.wells_data)
    except Exception:
        traceback.print_exc(file=stderr_buffer)

    result.stdout_text = stdout_buffer.getvalue()
    result.stderr_text = stderr_buffer.getvalue()
    return result
