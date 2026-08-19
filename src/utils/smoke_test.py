from __future__ import annotations

import io
import re
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Dict, List

from src.utils.app_paths import ensure_runtime_layout, get_input_dir

MISSING_TOKENS = {"", "-", "не найдено", "ошибка", "nan", "none"}


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    text = str(value).strip().lower()
    return text in MISSING_TOKENS


def _as_float(value: object):
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return None


def _validate_dates(start_date: object, end_date: object) -> bool:
    pattern = re.compile(r"^\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}$")
    return bool(pattern.match(str(start_date).strip())) and bool(pattern.match(str(end_date).strip()))


def run_smoke_test(max_files: int = 2) -> Dict[str, object]:
    ensure_runtime_layout(copy_reference=True)

    from src.extractors.main_parser import FinalUnifiedParser

    input_dir = get_input_dir()
    pdf_files = sorted(input_dir.glob("*.pdf"))[:max_files]
    if not pdf_files:
        module_errors: List[str] = []
        try:
            from src.extractors.main_parser import FinalUnifiedParser
            FinalUnifiedParser()
        except Exception as exc:
            module_errors.append(f"main_parser import/init failed ({exc})")
        try:
            from src.extractors import table_parser  # noqa: F401
        except Exception as exc:
            module_errors.append(f"table_parser import failed ({exc})")
        try:
            from src.extractors import km_parser  # noqa: F401
        except Exception as exc:
            module_errors.append(f"km_parser import failed ({exc})")
        try:
            from integral import IntegralCoefficientCalculator
            IntegralCoefficientCalculator()
        except Exception as exc:
            module_errors.append(f"integral import/init failed ({exc})")

        if module_errors:
            return {
                "ok": False,
                "checked": 0,
                "errors": [f"No PDF files found in {input_dir}"] + module_errors,
                "details": [],
                "warning": "No PDF fixtures were available for full smoke test.",
            }
        return {
            "ok": True,
            "checked": 0,
            "errors": [],
            "details": [],
            "warning": f"No PDF files found in {input_dir}. Only module import smoke test was executed.",
        }

    parser = FinalUnifiedParser()
    details: List[Dict[str, object]] = []
    errors: List[str] = []

    for pdf_path in pdf_files:
        item = {
            "file": pdf_path.name,
            "core_ok": True,
            "modules_ok": True,
            "missing": [],
        }

        try:
            well = parser.parse_all(str(pdf_path))
        except Exception as exc:
            errors.append(f"{pdf_path.name}: parse_all failed ({exc})")
            item["core_ok"] = False
            details.append(item)
            continue

        for field_name in ("temperature", "angle", "start_date", "end_date"):
            if _is_missing(getattr(well, field_name, "")):
                item["core_ok"] = False
                item["missing"].append(field_name)

        if _is_missing(getattr(well, "volume", "")) and _is_missing(getattr(well, "spo", "")):
            item["core_ok"] = False
            item["missing"].append("volume_or_spo")

        if not _validate_dates(getattr(well, "start_date", ""), getattr(well, "end_date", "")):
            item["core_ok"] = False
            item["missing"].append("date_format")

        temperature = _as_float(getattr(well, "temperature", ""))
        angle = _as_float(getattr(well, "angle", ""))
        if temperature is None or angle is None:
            item["core_ok"] = False
            item["missing"].append("integral_inputs")

        module_errors: List[str] = []
        try:
            from src.extractors import table_parser
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                table_parser.analyze_from_pdf(pdf_path)
        except Exception as exc:
            module_errors.append(f"table_parser failed ({exc})")

        try:
            from src.extractors import km_parser
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                km_parser.process_pdf(pdf_path)
        except Exception as exc:
            module_errors.append(f"km_parser failed ({exc})")

        try:
            from integral import IntegralCoefficientCalculator
            calc = IntegralCoefficientCalculator()
            calc.coefficient_table.get_integral_coefficient(temperature or 0.0, angle or 0.0)
        except Exception as exc:
            module_errors.append(f"integral failed ({exc})")

        if module_errors:
            item["modules_ok"] = False
            item["module_errors"] = module_errors

        if not item["core_ok"]:
            missing = ", ".join(item["missing"])
            errors.append(f"{pdf_path.name}: missing or invalid fields ({missing})")
        if not item["modules_ok"]:
            errors.append(f"{pdf_path.name}: " + "; ".join(item.get("module_errors", [])))

        details.append(item)

    return {
        "ok": len(errors) == 0,
        "checked": len(details),
        "errors": errors,
        "details": details,
    }


def format_smoke_report(result: Dict[str, object]) -> str:
    lines = []
    lines.append(f"SMOKE TEST STATUS: {'OK' if result.get('ok') else 'FAILED'}")
    lines.append(f"Checked files: {result.get('checked', 0)}")
    warning = result.get("warning")
    if warning:
        lines.append(f"Warning: {warning}")

    details = result.get("details", [])
    for item in details:
        status = "OK" if item.get("core_ok") and item.get("modules_ok") else "FAIL"
        lines.append(f"- {item.get('file')}: {status}")
        missing = item.get("missing") or []
        if missing:
            lines.append(f"  missing: {', '.join(missing)}")
        module_errors = item.get("module_errors") or []
        for err in module_errors:
            lines.append(f"  module: {err}")

    errors = result.get("errors") or []
    if errors:
        lines.append("Errors:")
        for err in errors:
            lines.append(f"- {err}")

    return "\n".join(lines)


def main() -> int:
    result = run_smoke_test(max_files=2)
    print(format_smoke_report(result))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
