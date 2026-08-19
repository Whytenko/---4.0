from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.utils.app_paths import (
    ensure_runtime_layout,
    get_bundled_ml_data_csv,
    get_input_dir,
    get_logs_dir,
    get_ml_models_dir,
    get_reference_dir,
    get_resource_roots,
    get_runtime_root,
)


@dataclass
class CheckItem:
    name: str
    status: str
    detail: str
    path: str = ""
    hint: str = ""


REQUIRED_REFERENCE_FILES = (
    "17. Отчет по километражу.xlsx",
    "Стоимость ВМ задачи (не удалять).xlsx",
    "tabale_rascenki.csv",
)


def _item(name: str, status: str, detail: str, path: Path | None = None, hint: str = "") -> CheckItem:
    return CheckItem(
        name=name,
        status=status,
        detail=detail,
        path=str(path) if path else "",
        hint=hint,
    )


def _write_probe(directory: Path) -> bool:
    probe = directory / ".write_probe"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def _find_tesseract_cmd() -> Optional[Path]:
    candidates: List[Path] = []

    try:
        in_path = shutil.which("tesseract")
        if in_path:
            candidates.append(Path(in_path))
    except Exception:
        pass

    for root in get_resource_roots():
        candidates.extend(
            [
                root / "tesseract" / "tesseract",
                root / "tesseract" / "tesseract.exe",
                root / "tesseract" / "bin" / "tesseract",
                root / "tesseract" / "bin" / "tesseract.exe",
            ]
        )

    if os.name == "nt":
        candidates.extend(
            [
                Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
                Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
            ]
        )
    else:
        candidates.extend([Path("/opt/homebrew/bin/tesseract"), Path("/usr/local/bin/tesseract")])

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists():
            return candidate

    return None


def _find_tessdata_dir(cmd_path: Path) -> Optional[Path]:
    env_path = os.environ.get("TESSDATA_PREFIX", "").strip()
    if env_path:
        candidate = Path(env_path)
        if candidate.exists():
            return candidate

    candidates = [
        cmd_path.parent / "tessdata",
        cmd_path.parent.parent / "tessdata",
        Path("/usr/local/share/tessdata"),
        Path("/usr/share/tessdata"),
        Path("/usr/share/tesseract-ocr/4.00/tessdata"),
        Path("/usr/share/tesseract-ocr/5/tessdata"),
        Path("/opt/homebrew/share/tessdata"),
    ]
    for root in get_resource_roots():
        candidates.extend(
            [
                root / "tesseract" / "tessdata",
                root / "tesseract" / "bin" / "tessdata",
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def run_self_check(write_logs: bool = True) -> Dict[str, object]:
    ensure_runtime_layout(copy_reference=True)

    checks: List[CheckItem] = []
    runtime_root = get_runtime_root()
    input_dir = get_input_dir()
    ref_dir = get_reference_dir()
    logs_dir = get_logs_dir()
    models_dir = get_ml_models_dir()

    for name, path in (
        ("runtime_root", runtime_root),
        ("input_dir", input_dir),
        ("reference_dir", ref_dir),
        ("logs_dir", logs_dir),
        ("ml_models_dir", models_dir),
    ):
        if not path.exists():
            checks.append(_item(name, "error", "Directory is missing", path, "Reinstall package or recreate runtime layout."))
            continue
        if not _write_probe(path):
            checks.append(_item(name, "error", "Directory is not writable", path, "Check user permissions for this folder."))
            continue
        checks.append(_item(name, "ok", "Directory exists and writable", path))

    for filename in REQUIRED_REFERENCE_FILES:
        file_path = ref_dir / filename
        if file_path.exists():
            checks.append(_item(f"reference:{filename}", "ok", "Reference file exists", file_path))
        else:
            checks.append(
                _item(
                    f"reference:{filename}",
                    "error",
                    "Required reference file not found",
                    file_path,
                    "Copy reference file to runtime/reference or reinstall package.",
                )
            )

    temp_files = sorted(ref_dir.glob("20. Отчет по температуре*.xlsx"))
    if temp_files:
        checks.append(_item("reference:temperature", "ok", f"Found {len(temp_files)} temperature table(s)", temp_files[0]))
    else:
        checks.append(
            _item(
                "reference:temperature",
                "error",
                "Temperature table file is missing",
                ref_dir,
                "Add 20. Отчет по температуре.xlsx (or 2026 variant).",
            )
        )

    ml_csv = get_bundled_ml_data_csv()
    if ml_csv.exists():
        checks.append(_item("ml:training_csv", "ok", "ML training CSV found", ml_csv))
    else:
        checks.append(
            _item(
                "ml:training_csv",
                "warn",
                "ML training CSV not found. Exact-file fallback may not work.",
                ml_csv,
                "Place MLdata(Лист1)-2.csv near app resources.",
            )
        )

    model_files = sorted(models_dir.glob("*.joblib"))
    metadata = models_dir / "metadata.json"
    if model_files and metadata.exists():
        checks.append(_item("ml:line_models", "ok", f"Loaded {len(model_files)} trained line model(s)", models_dir))
    elif model_files:
        checks.append(
            _item(
                "ml:line_models",
                "warn",
                f"Found {len(model_files)} model file(s), metadata.json missing.",
                models_dir,
                "Retrain models to regenerate metadata.",
            )
        )
    else:
        checks.append(
            _item(
                "ml:line_models",
                "warn",
                "No line models found. OCR parser fallback is used.",
                models_dir,
                "Run ml_line_models training if you need ML line extraction.",
            )
        )

    tesseract_cmd = _find_tesseract_cmd()
    if not tesseract_cmd:
        checks.append(
            _item(
                "ocr:tesseract",
                "error",
                "Tesseract executable not found",
                None,
                "Bundle tesseract with app or install it in system PATH.",
            )
        )
    else:
        try:
            version_run = subprocess.run(
                [str(tesseract_cmd), "--version"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if version_run.returncode == 0:
                ver = (version_run.stdout or "").splitlines()[0] if version_run.stdout else "version check ok"
                checks.append(_item("ocr:tesseract", "ok", ver.strip(), tesseract_cmd))
            else:
                checks.append(
                    _item(
                        "ocr:tesseract",
                        "warn",
                        "Tesseract found, but version command failed",
                        tesseract_cmd,
                        "Check executable integrity.",
                    )
                )
        except Exception as exc:
            checks.append(
                _item(
                    "ocr:tesseract",
                    "warn",
                    f"Tesseract command check failed: {exc}",
                    tesseract_cmd,
                )
            )

        tessdata_dir = _find_tessdata_dir(tesseract_cmd)
        if tessdata_dir is None:
            checks.append(
                _item(
                    "ocr:tessdata",
                    "error",
                    "tessdata folder not found",
                    tesseract_cmd.parent,
                    "Bundle tessdata next to tesseract executable.",
                )
            )
        else:
            checks.append(_item("ocr:tessdata", "ok", "tessdata folder found", tessdata_dir))
            for lang in ("rus", "eng"):
                lang_file = tessdata_dir / f"{lang}.traineddata"
                if lang_file.exists():
                    checks.append(_item(f"ocr:lang:{lang}", "ok", "Language pack found", lang_file))
                else:
                    checks.append(
                        _item(
                            f"ocr:lang:{lang}",
                            "error",
                            "Language pack missing",
                            lang_file,
                            f"Add {lang}.traineddata to tessdata folder.",
                        )
                    )

    pdf_count = len(list(input_dir.glob("*.pdf")))
    if pdf_count > 0:
        checks.append(_item("input:pdf", "ok", f"Found {pdf_count} PDF file(s)", input_dir))
    else:
        checks.append(_item("input:pdf", "warn", "No PDF files in input folder", input_dir, "Copy PDF files into input folder."))

    error_count = sum(1 for c in checks if c.status == "error")
    warn_count = sum(1 for c in checks if c.status == "warn")
    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "runtime_root": str(runtime_root),
        "ok": error_count == 0,
        "status": "ok" if error_count == 0 and warn_count == 0 else ("warn" if error_count == 0 else "error"),
        "errors": error_count,
        "warnings": warn_count,
        "checks": [asdict(c) for c in checks],
    }

    if write_logs:
        _write_self_check_logs(result)

    return result


def _write_self_check_logs(result: Dict[str, object]) -> None:
    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)

    json_path = logs_dir / "self_check_latest.json"
    txt_path = logs_dir / "self_check_latest.txt"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(format_self_check_report(result, with_hints=True), encoding="utf-8")


def format_self_check_report(result: Dict[str, object], with_hints: bool = False) -> str:
    lines = []
    status = str(result.get("status", "unknown")).upper()
    lines.append(f"SELF-CHECK STATUS: {status}")
    lines.append(f"Timestamp: {result.get('timestamp', '')}")
    lines.append(f"Runtime root: {result.get('runtime_root', '')}")
    lines.append(f"Errors: {result.get('errors', 0)} | Warnings: {result.get('warnings', 0)}")
    lines.append("")

    checks = result.get("checks", [])
    for row in checks:
        item_status = str(row.get("status", "")).upper()
        name = row.get("name", "")
        detail = row.get("detail", "")
        path = row.get("path", "")
        lines.append(f"[{item_status}] {name}: {detail}")
        if path:
            lines.append(f"  path: {path}")
        hint = row.get("hint", "")
        if with_hints and hint:
            lines.append(f"  hint: {hint}")
    return "\n".join(lines)


def main() -> int:
    result = run_self_check(write_logs=True)
    print(format_self_check_report(result, with_hints=True))
    return 0 if result.get("errors", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
