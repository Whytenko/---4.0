from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple
import math
import os
import re

import pandas as pd

from src.utils.app_paths import ensure_runtime_layout, get_bundled_ml_data_csv, get_ml_cache_dir

RAW_DATA_PATH = get_bundled_ml_data_csv()
CLEAN_DATA_PATH = get_ml_cache_dir() / "mldata_clean.csv"

DATE_COLUMNS = (
    "start_date_page1",
    "end_date_page1",
    "start_date_page2",
    "end_date_page2",
)

NUMERIC_COLUMNS = (
    "temperature_air",
    "angle",
    "well_bush",
    "volume_sum_page1",
    "volume_sum_page3",
    "sp_openhole_page1",
    "sp_template_page1",
    "sp_nkt_page1",
    "sp_torp_page1",
    "sp_table_end",
    "km_reloc_1gr",
    "km_reloc_3gr",
    "vm_price",
    "vm_count",
)

FEATURE_COLUMNS = (
    "temperature_air",
    "angle",
    "well_bush",
    "volume_sum_page1",
    "volume_sum_page3",
    "vm_price",
    "vm_count",
    "duration_hours",
)

FIELD_MAPPING = {
    "field": ("field", "str"),
    "order": ("order", "int"),
    "temperature_air": ("temperature", "float"),
    "angle": ("angle", "float"),
    "start_date_page1": ("start_date", "date"),
    "end_date_page1": ("end_date", "date"),
    "start_date_page2": ("page2_start", "date"),
    "end_date_page2": ("page2_end", "date"),
    "volume_sum_page1": ("volume_sum_page1", "float"),
    "volume_sum_page3": ("qty_sum_page3", "float"),
    "sp_table_end": ("spo", "float"),
    "vm_price": ("vm_price", "float"),
    "vm_count": ("vm_count", "int"),
}

MISSING_TOKENS = {"", "-", "не найдено", "ошибка", "nan", "none"}


def _normalize_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _parse_ru_float(value: Optional[object]) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if _normalize_text(text) in MISSING_TOKENS:
        return None
    text = text.replace("\u00a0", "").replace(" ", "")
    text = text.replace(",", ".")
    try:
        return float(text)
    except Exception:
        return None


def _parse_ru_int(value: Optional[object]) -> Optional[int]:
    parsed = _parse_ru_float(value)
    if parsed is None:
        return None
    try:
        return int(round(parsed))
    except Exception:
        return None


def _parse_order_str(value: Optional[object]) -> str:
    if value is None:
        return ""
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return ""
        return str(int(value))
    text = str(value).strip()
    if text.endswith(".0") and text.replace(".", "").isdigit():
        return text.split(".")[0]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits


def _parse_date(value: Optional[object]) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if _normalize_text(text) in MISSING_TOKENS:
        return None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _format_decimal(value: float, decimals: int = 2) -> str:
    fmt = f"{{:.{decimals}f}}"
    return fmt.format(value).replace(".", ",")


def _format_value(value: Optional[object], field_type: str) -> str:
    if value is None:
        return ""
    if field_type == "int":
        parsed = _parse_ru_int(value)
        return str(parsed) if parsed is not None else ""
    if field_type == "float":
        parsed = _parse_ru_float(value)
        if parsed is None:
            return ""
        return _format_decimal(parsed, 2)
    if field_type == "date":
        if isinstance(value, datetime):
            return value.strftime("%d.%m.%Y %H:%M")
        parsed = _parse_date(value)
        return parsed.strftime("%d.%m.%Y %H:%M") if parsed else ""
    return str(value).strip()


def _choose_spo_from_row(row: pd.Series) -> tuple[Optional[float], str]:
    values = []
    sources = []
    for key in ("sp_openhole_page1", "sp_template_page1", "sp_nkt_page1", "sp_torp_page1"):
        if key not in row:
            continue
        value = row.get(key)
        parsed = _parse_ru_float(value)
        if parsed is not None:
            values.append(parsed)
            sources.append(key)
    if not values:
        return None, ""
    return sum(values), " + ".join(sources)


def _is_missing(value: Optional[object]) -> bool:
    if value is None:
        return True
    return _normalize_text(value) in MISSING_TOKENS


def _safe_range(series: pd.Series) -> float:
    if series.empty:
        return 1.0
    min_val = series.min()
    max_val = series.max()
    if pd.isna(min_val) or pd.isna(max_val):
        return 1.0
    diff = max_val - min_val
    return diff if diff > 0 else 1.0


def clean_mldata(raw_path: Path = RAW_DATA_PATH,
                 clean_path: Path = CLEAN_DATA_PATH,
                 write: bool = True) -> Optional[pd.DataFrame]:
    if not raw_path.exists():
        return None
    df = pd.read_csv(raw_path, sep=";", encoding="utf-8-sig")
    if "file" not in df.columns:
        return None
    df = df[df["file"].notna()].copy()
    df["file"] = df["file"].astype(str).str.replace(".pdf", "", regex=False)
    df["field"] = df["field"].astype(str).str.strip()
    df["order"] = df["order"].apply(_parse_order_str)

    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(_parse_ru_float)

    for col in DATE_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(_parse_date)

    df["duration_hours"] = None
    if "start_date_page1" in df.columns and "end_date_page1" in df.columns:
        durations = []
        for start, end in zip(df["start_date_page1"], df["end_date_page1"]):
            if isinstance(start, datetime) and isinstance(end, datetime):
                durations.append((end - start).total_seconds() / 3600)
            else:
                durations.append(None)
        df["duration_hours"] = durations

    if write:
        export = df.copy()
        for col in DATE_COLUMNS:
            if col in export.columns:
                export[col] = export[col].apply(
                    lambda d: d.strftime("%Y-%m-%d %H:%M") if isinstance(d, datetime) else ""
                )
        try:
            clean_path.parent.mkdir(parents=True, exist_ok=True)
            export.to_csv(clean_path, index=False)
        except Exception:
            pass

    return df


@dataclass
class MLMatchResult:
    row: pd.Series
    confidence: float
    method: str


class MLAssist:
    _instance: Optional["MLAssist"] = None

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.ranges = {
            col: _safe_range(df[col].dropna()) for col in FEATURE_COLUMNS if col in df.columns
        }

    @classmethod
    def load(cls) -> Optional["MLAssist"]:
        ensure_runtime_layout(copy_reference=False)
        if cls._instance is not None:
            return cls._instance
        df = clean_mldata()
        if df is None or df.empty:
            return None
        cls._instance = MLAssist(df)
        return cls._instance

    def match_exact(self, well_data) -> Optional[MLMatchResult]:
        """Возвращает матч только по точному имени файла; knn не запускается."""
        file_base = Path(getattr(well_data, "filename", "")).stem
        if not file_base:
            return None
        exact = self.df[self.df["file"] == file_base]
        if exact.empty:
            return None
        return MLMatchResult(row=exact.iloc[0], confidence=1.0, method="exact-file")

    def match(self, well_data) -> Optional[MLMatchResult]:
        """Exact-file match + knn fallback. Используй match_exact() если knn не нужен."""
        result = self.match_exact(well_data)
        if result is not None:
            return result

        query = self._build_query(well_data)
        best_row = None
        best_score = None
        for _, row in self.df.iterrows():
            score = self._similarity(query, row)
            if score is None:
                continue
            if best_score is None or score > best_score:
                best_score = score
                best_row = row

        if best_row is None or best_score is None:
            return None
        return MLMatchResult(row=best_row, confidence=best_score, method="knn")

    def _build_query(self, well_data) -> Dict[str, Optional[object]]:
        def _get(attr: str) -> Optional[object]:
            return getattr(well_data, attr, None)

        start_dt = _parse_date(_get("start_date"))
        end_dt = _parse_date(_get("end_date"))
        duration = None
        if isinstance(start_dt, datetime) and isinstance(end_dt, datetime):
            duration = (end_dt - start_dt).total_seconds() / 3600

        return {
            "field": _normalize_text(_get("field")),
            "order": _parse_order_str(_get("order")),
            "temperature_air": _parse_ru_float(_get("temperature")),
            "angle": _parse_ru_float(_get("angle")),
            "well_bush": _parse_ru_int(_get("well_bush")),
            "volume_sum_page1": _parse_ru_float(_get("volume_sum_page1")),
            "volume_sum_page3": _parse_ru_float(_get("qty_sum_page3")),
            "vm_price": _parse_ru_float(_get("vm_price")),
            "vm_count": _parse_ru_float(_get("vm_count")),
            "duration_hours": duration,
        }

    def _similarity(self, query: Dict[str, Optional[object]], row: pd.Series) -> Optional[float]:
        diffs = []
        for col in FEATURE_COLUMNS:
            if col not in row:
                continue
            qv = query.get(col)
            rv = row.get(col)
            if qv is None or rv is None or pd.isna(rv):
                continue
            denom = self.ranges.get(col, 1.0)
            diffs.append(abs(qv - rv) / denom)

        if not diffs:
            return None

        distance = sum(diffs) / len(diffs)

        if query.get("field") and row.get("field"):
            if query["field"] != str(row["field"]).strip().lower():
                distance += 0.5
        if query.get("order") and row.get("order"):
            if query["order"] != str(row["order"]).strip():
                distance += 0.5

        return 1.0 / (1.0 + distance)


def _choose_spo_from_dict(values: Dict[str, object]) -> tuple[Optional[float], str]:
    parts = []
    sources = []
    for key in ("sp_openhole_page1", "sp_template_page1", "sp_nkt_page1", "sp_torp_page1"):
        if key not in values:
            continue
        parsed = _parse_ru_float(values.get(key))
        if parsed is not None:
            parts.append(parsed)
            sources.append(key)
    if not parts:
        return None, ""
    return sum(parts), " + ".join(sources)


def _apply_vm_table_price(well_data, applied: Dict[str, Tuple[str, str]], suggestions: Dict[str, str]) -> None:
    task = getattr(well_data, "vm_task", "")
    if not task:
        return
    try:
        max_price, min_price = well_data._get_vm_prices(task, None)
    except Exception:
        return
    price = min_price if min_price is not None else max_price
    if price is None:
        return
    formatted = _format_value(price, "float")
    current = getattr(well_data, "vm_price", None)
    if str(current) == formatted:
        return
    setattr(well_data, "vm_price", formatted)
    applied["vm_price"] = ("" if _is_missing(current) else str(current), formatted)
    suggestions["vm_price"] = formatted


def apply_ml_fallback(well_data, min_confidence: float = 0.65, pdf_path: Optional[str] = None) -> None:
    if os.environ.get("AKT_DISABLE_ML") == "1":
        return
    assist = MLAssist.load()
    if assist is None:
        return

    # Только exact-file match применяется для коррекции данных.
    # knn-поиск пропускается — его результат всё равно не использовался.
    match = assist.match_exact(well_data)
    if match is None:
        _apply_ml_line_extraction(well_data, pdf_path)
        return
    if match.confidence < 0.9:
        return

    force_override = True  # exact-file всегда имеет confidence=1.0

    suggestions: Dict[str, str] = {}
    applied: Dict[str, Tuple[str, str]] = {}

    spo_value, spo_source = _choose_spo_from_row(match.row)
    if spo_value is not None:
        formatted_spo = _format_value(spo_value, "float")
        current_spo = getattr(well_data, "volume", None)
        if force_override:
            if str(current_spo) != formatted_spo:
                setattr(well_data, "volume", formatted_spo)
                applied["volume"] = ("" if _is_missing(current_spo) else str(current_spo), formatted_spo)
                if spo_source:
                    well_data.ml_spo_source = spo_source
            suggestions["volume"] = formatted_spo
        else:
            if _is_missing(current_spo):
                setattr(well_data, "volume", formatted_spo)
                applied["volume"] = ("", formatted_spo)
                suggestions["volume"] = formatted_spo
                if spo_source:
                    well_data.ml_spo_source = spo_source

    for src_field, (attr, field_type) in FIELD_MAPPING.items():
        if src_field not in match.row:
            continue
        raw_value = match.row.get(src_field)
        if raw_value is None or (isinstance(raw_value, float) and math.isnan(raw_value)):
            continue
        formatted = _format_value(raw_value, field_type)
        if not formatted:
            continue

        current = getattr(well_data, attr, None)
        suggestions[attr] = formatted

        if force_override:
            if str(current) != formatted:
                setattr(well_data, attr, formatted)
                applied[attr] = ("" if _is_missing(current) else str(current), formatted)
            continue

        if _is_missing(current):
            setattr(well_data, attr, formatted)
            applied[attr] = ("", formatted)
            continue

        if field_type in {"float", "int"}:
            current_val = _parse_ru_float(current)
            new_val = _parse_ru_float(formatted)
            if current_val is None or new_val is None:
                setattr(well_data, attr, formatted)
                applied[attr] = (str(current), formatted)
                continue
            if abs(current_val - new_val) > max(0.5, abs(new_val) * 0.25):
                setattr(well_data, attr, formatted)
                applied[attr] = (str(current), formatted)
                continue
        if field_type == "date":
            if _parse_date(current) is None:
                setattr(well_data, attr, formatted)
                applied[attr] = (str(current), formatted)

    _apply_vm_table_price(well_data, applied, suggestions)

    if applied:
        well_data.ml_confidence = match.confidence
        well_data.ml_method = match.method
        well_data.ml_suggestions = suggestions
        well_data.ml_applied = applied
        try:
            well_data.duration_hours = well_data._calculate_duration()
        except Exception:
            pass


def _apply_ml_line_extraction(well_data, pdf_path: Optional[str]) -> None:
    if not pdf_path:
        return
    try:
        from ml_line_models import MLLinePredictor
    except Exception:
        return
    predictor = MLLinePredictor.get_cached()
    if not predictor.available():
        return

    ocr_enabled = os.environ.get("AKT_ML_OCR", "1") != "0"
    ocr_pages = [6, 7, 8, 9]
    if ocr_enabled:
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                total = len(pdf.pages)
            if total > 0:
                tail = list(range(max(1, total - 3), total + 1))
                ocr_pages = sorted(set(ocr_pages + tail))
        except Exception:
            pass
    values, probs = predictor.extract_from_pdf(Path(pdf_path), ocr=ocr_enabled, ocr_pages=ocr_pages)
    if not values:
        return

    applied: Dict[str, Tuple[str, str]] = {}
    suggestions: Dict[str, str] = {}

    spo_value, spo_source = _choose_spo_from_dict(values)
    spo_confident = True
    if spo_value is not None:
        for key in ("sp_openhole_page1", "sp_template_page1", "sp_nkt_page1", "sp_torp_page1"):
            if key in values and probs.get(key, 0.0) < 0.9:
                spo_confident = False
                break
    if spo_value is not None and spo_confident:
        formatted = _format_value(spo_value, "float")
        current = getattr(well_data, "volume", None)
        if str(current) != formatted:
            setattr(well_data, "volume", formatted)
            applied["volume"] = ("" if _is_missing(current) else str(current), formatted)
            suggestions["volume"] = formatted
            well_data.ml_spo_source = spo_source

    sp_table = values.get("sp_table_end")
    if sp_table is not None and probs.get("sp_table_end", 0.0) >= 0.9:
        formatted = _format_value(sp_table, "float")
        current = getattr(well_data, "spo", None)
        if str(current) != formatted:
            setattr(well_data, "spo", formatted)
            applied["spo"] = ("" if _is_missing(current) else str(current), formatted)
            suggestions["spo"] = formatted
    else:
        ocr_spo = _extract_sp_table_end_ocr(pdf_path) if ocr_enabled else None
        if ocr_spo is not None:
            formatted = _format_value(ocr_spo, "float")
            current = getattr(well_data, "spo", None)
            if str(current) != formatted:
                setattr(well_data, "spo", formatted)
                applied["spo"] = ("" if _is_missing(current) else str(current), formatted)
                suggestions["spo"] = formatted

    for src_field, (attr, field_type) in FIELD_MAPPING.items():
        if src_field not in values:
            continue
        if probs.get(src_field, 0.0) < 0.9:
            continue
        raw_value = values.get(src_field)
        if raw_value is None:
            continue
        formatted = _format_value(raw_value, field_type)
        if not formatted:
            continue
        current = getattr(well_data, attr, None)
        if str(current) == formatted:
            continue
        setattr(well_data, attr, formatted)
        applied[attr] = ("" if _is_missing(current) else str(current), formatted)
        suggestions[attr] = formatted

    _apply_vm_table_price(well_data, applied, suggestions)

    if applied:
        well_data.ml_method = "ml-lines"
        if probs:
            well_data.ml_confidence = sum(probs.values()) / len(probs)
        well_data.ml_suggestions = suggestions
        well_data.ml_applied = applied
        try:
            well_data.duration_hours = well_data._calculate_duration()
        except Exception:
            pass


def _extract_sp_table_end_ocr(pdf_path: str) -> Optional[float]:
    try:
        import pdfplumber
        import pytesseract
        from PIL import ImageOps
    except Exception:
        return None
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages
            if not pages:
                return None
            scan_pages = pages[-4:] if len(pages) > 4 else pages
            for page in scan_pages:
                h = page.height
                w = page.width
                crops = [
                    (0, h * 0.75, w, h * 0.98),  # нижняя полоса (обычно СПО)
                    (w * 0.30, h * 0.70, w * 0.80, h * 0.92),  # центр-низ с таблицей
                    (w * 0.10, h * 0.70, w * 0.90, h * 0.92),
                ]
                for crop_box in crops:
                    crop = page.crop(crop_box)
                    image = crop.to_image(resolution=300).original
                    gray = ImageOps.grayscale(image)
                    gray = ImageOps.autocontrast(gray)
                    text = pytesseract.image_to_string(
                        gray,
                        lang="rus+eng",
                        config="--psm 6 -c tessedit_char_whitelist=СПОspoSPO0123456789.,:мMm ",
                        timeout=8,
                    )
                    value = _extract_sp_table_from_text(text)
                    if value is not None:
                        return value
    except Exception:
        return None
    return None


def _extract_sp_table_from_text(text: str) -> Optional[float]:
    normalized = (
        text.replace("C", "С")
        .replace("P", "Р")
        .replace("c", "с")
        .replace("p", "р")
    )
    pattern = re.compile(r"\bСПО\s*[:=]\s*([0-9OО\s]+[.,][0-9OО]{1,2}|[0-9OО]+)", re.IGNORECASE)
    values = []
    for match in pattern.finditer(normalized):
        value = match.group(1).replace(" ", "").replace(",", ".")
        value = value.replace("O", "0").replace("О", "0")
        try:
            values.append(float(value))
        except Exception:
            continue
    if not values:
        return None
    return max(values)


if __name__ == "__main__":
    df = clean_mldata()
    if df is None:
        print("MLdata CSV не найден или не распознан.")
    else:
        print(f"Готово: {len(df)} строк")
        print(f"Файл: {CLEAN_DATA_PATH}")
