from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_DIR_NAME = "AktNaryadVerifier"
ENV_HOME_KEY = "AKT_NARYAD_HOME"


def _user_data_base_dir() -> Path:
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data)
        return Path.home() / "AppData" / "Local"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home)
    return Path.home() / ".local" / "share"


def get_runtime_root() -> Path:
    override = os.environ.get(ENV_HOME_KEY, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (_user_data_base_dir() / APP_DIR_NAME).resolve()


def get_input_dir() -> Path:
    return get_runtime_root() / "input"


def get_reference_dir() -> Path:
    return get_runtime_root() / "reference"


def get_output_dir() -> Path:
    return get_runtime_root() / "output"


def get_logs_dir() -> Path:
    return get_runtime_root() / "logs"


def get_ml_cache_dir() -> Path:
    return get_runtime_root() / "ml_cache"


def get_ml_models_dir() -> Path:
    return get_ml_cache_dir() / "models"


def get_resource_roots() -> list[Path]:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path(__file__).resolve().parents[2])

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def get_bundled_reference_dir() -> Path:
    for root in get_resource_roots():
        candidate = root / "data" / "reference"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[2] / "data" / "reference"


def get_bundled_input_dir() -> Path:
    for root in get_resource_roots():
        candidate = root / "data" / "input"
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[2] / "data" / "input"


def get_bundled_ml_data_csv() -> Path:
    filename = "MLdata(Лист1)-2.csv"
    for root in get_resource_roots():
        candidate = root / filename
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[2] / filename


def ensure_runtime_layout(copy_reference: bool = True) -> Path:
    runtime_root = get_runtime_root()
    for directory in (
        runtime_root,
        get_input_dir(),
        get_reference_dir(),
        get_output_dir(),
        get_logs_dir(),
        get_ml_cache_dir(),
        get_ml_models_dir(),
    ):
        directory.mkdir(parents=True, exist_ok=True)

    if copy_reference:
        src_dir = get_bundled_reference_dir()
        dst_dir = get_reference_dir()
        if src_dir.exists():
            for src in src_dir.glob("*"):
                if not src.is_file():
                    continue
                dst = dst_dir / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)

    src_input_dir = get_bundled_input_dir()
    dst_input_dir = get_input_dir()
    if src_input_dir.exists() and not any(dst_input_dir.glob("*.pdf")):
        for src_pdf in src_input_dir.glob("*.pdf"):
            dst_pdf = dst_input_dir / src_pdf.name
            if not dst_pdf.exists():
                shutil.copy2(src_pdf, dst_pdf)

    return runtime_root
