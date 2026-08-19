from __future__ import annotations

import argparse
import json
import math
import re
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from src.utils.app_paths import (
    ensure_runtime_layout,
    get_bundled_ml_data_csv,
    get_input_dir,
    get_ml_models_dir,
    get_resource_roots,
)

RAW_CSV_PATH = get_bundled_ml_data_csv()
INPUT_DIR = get_input_dir()
MODEL_DIR = get_ml_models_dir()

FIELD_DEFS = {
    "field": "str",
    "order": "int",
    "temperature_air": "float",
    "angle": "float",
    "well_bush": "int",
    "start_date_page1": "date",
    "end_date_page1": "date",
    "start_date_page2": "date",
    "end_date_page2": "date",
    "volume_sum_page1": "float",
    "volume_sum_page3": "float",
    "sp_openhole_page1": "float",
    "sp_template_page1": "float",
    "sp_nkt_page1": "float",
    "sp_torp_page1": "float",
    "sp_table_end": "float",
    "km_reloc_1gr": "float",
    "km_reloc_3gr": "float",
    "vm_price": "float",
    "vm_count": "int",
}

MISSING_TOKENS = {"", "-", "не найдено", "ошибка", "nan", "none"}


@dataclass
class LineItem:
    text: str
    page: int


@dataclass
class ModelPackage:
    field: str
    vectorizer: object
    model: object


class LineExtractor:
    def __init__(self, ocr: bool = False, ocr_pages: Optional[List[int]] = None):
        self.ocr = ocr
        self.ocr_pages = ocr_pages or []

    def extract_lines(self, pdf_path: Path) -> List[LineItem]:
        lines: List[LineItem] = []
        try:
            import pdfplumber
        except Exception:
            return lines

        with pdfplumber.open(pdf_path) as pdf:
            for idx, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                page_no = idx + 1
                if (self.ocr and not text.strip()) or (self.ocr and page_no in self.ocr_pages):
                    text = self._ocr_page(page)
                if not text:
                    continue
                for raw_line in text.splitlines():
                    line = " ".join(raw_line.split()).strip()
                    if line:
                        lines.append(LineItem(text=line, page=idx + 1))
        return lines

    def _ocr_page(self, page) -> str:
        try:
            import pytesseract
            from PIL import ImageOps
        except Exception:
            return ""
        if not _configure_tesseract(pytesseract):
            return ""
        try:
            image = page.to_image(resolution=300).original
            gray = ImageOps.grayscale(image)
            gray = ImageOps.autocontrast(gray)
            return pytesseract.image_to_string(gray, lang="rus+eng", config="--psm 6")
        except Exception:
            return ""


def _configure_tesseract(pytesseract_module) -> bool:
    try:
        current_cmd = str(getattr(pytesseract_module.pytesseract, "tesseract_cmd", "")).strip()
        if current_cmd and Path(current_cmd).exists():
            cmd_path = Path(current_cmd)
            for tessdata in (cmd_path.parent / "tessdata", cmd_path.parent.parent / "tessdata"):
                if tessdata.exists():
                    os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))
                    break
            return True
    except Exception:
        pass

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

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if not candidate.exists():
            continue
        try:
            pytesseract_module.pytesseract.tesseract_cmd = str(candidate)
            for tessdata in (candidate.parent / "tessdata", candidate.parent.parent / "tessdata"):
                if tessdata.exists():
                    os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))
                    break
            return True
        except Exception:
            continue
    return False


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
    text = text.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except Exception:
        return None


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


def _numbers_in_line(line: str) -> List[float]:
    tokens = re.findall(r"-?\d+[\.,]?\d*", line)
    numbers = []
    for token in tokens:
        try:
            num = float(token.replace(",", "."))
            numbers.append(num)
        except Exception:
            continue
    return numbers


def _line_has_date(line: str, target: datetime) -> bool:
    if not line:
        return False
    tokens = [
        target.strftime("%d.%m.%Y"),
        target.strftime("%d.%m.%y"),
        target.strftime("%d/%m/%Y"),
        target.strftime("%d/%m/%y"),
    ]
    lowered = line.lower()
    return any(token in lowered for token in tokens)


def _find_positive_lines(lines: List[LineItem], value: object, field_type: str) -> List[int]:
    indices: List[int] = []
    if field_type == "str":
        target = _normalize_text(value)
        if not target or target in MISSING_TOKENS:
            return indices
        for idx, line in enumerate(lines):
            if target in line.text.lower():
                indices.append(idx)
        return indices

    if field_type == "date":
        date_val = _parse_date(value)
        if date_val is None:
            return indices
        for idx, line in enumerate(lines):
            if _line_has_date(line.text, date_val):
                indices.append(idx)
        return indices

    target = _parse_ru_float(value)
    if target is None:
        return indices
    tolerance = 0.01 if field_type == "float" else 0.5
    for idx, line in enumerate(lines):
        nums = _numbers_in_line(line.text)
        for num in nums:
            if abs(num - target) <= tolerance:
                indices.append(idx)
                break
    return indices


def _sample_negatives(total: int, positives: Iterable[int], max_samples: int) -> List[int]:
    positives_set = set(positives)
    negatives = [i for i in range(total) if i not in positives_set]
    if len(negatives) <= max_samples:
        return negatives
    step = max(1, len(negatives) // max_samples)
    return negatives[::step][:max_samples]


def _ensure_models_dir() -> Path:
    ensure_runtime_layout(copy_reference=False)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    return MODEL_DIR


def _field_stats(df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    stats: Dict[str, Dict[str, float]] = {}
    for field, ftype in FIELD_DEFS.items():
        if ftype not in {"float", "int"}:
            continue
        if field not in df.columns:
            continue
        series = df[field].apply(_parse_ru_float).dropna()
        if series.empty:
            continue
        stats[field] = {
            "min": float(series.min()),
            "max": float(series.max()),
            "median": float(series.median()),
        }
    return stats


def _load_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, sep=";", encoding="utf-8-sig")
    if "file" not in df.columns:
        raise ValueError("CSV не содержит колонку file")
    df = df[df["file"].notna()].copy()
    return df


def train_models(csv_path: Path = RAW_CSV_PATH,
                 input_dir: Path = INPUT_DIR,
                 model_dir: Path = MODEL_DIR,
                 ocr: bool = False,
                 ocr_pages: Optional[List[int]] = None,
                 min_pos: int = 3,
                 max_neg_multiplier: int = 8) -> Dict[str, Dict[str, int]]:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        import joblib
    except Exception:
        raise RuntimeError("Требуется scikit-learn. Установите из requirements.txt")

    df = _load_csv(csv_path)
    extractor = LineExtractor(ocr=ocr, ocr_pages=ocr_pages)

    line_cache: Dict[str, List[LineItem]] = {}
    for file_base in sorted(df["file"].astype(str).unique()):
        pdf_path = input_dir / f"{file_base}.pdf"
        if not pdf_path.exists():
            continue
        lines = extractor.extract_lines(pdf_path)
        if lines:
            line_cache[file_base] = lines

    stats = _field_stats(df)
    report: Dict[str, Dict[str, int]] = {}
    model_dir = _ensure_models_dir()

    for field, ftype in FIELD_DEFS.items():
        positives: List[str] = []
        negatives: List[str] = []
        for _, row in df.iterrows():
            file_base = str(row["file"]).strip()
            if not file_base:
                continue
            lines = line_cache.get(file_base)
            if not lines:
                continue
            value = row.get(field)
            if _normalize_text(value) in MISSING_TOKENS:
                continue

            pos_idx = _find_positive_lines(lines, value, ftype)
            if not pos_idx:
                continue
            positives.extend([lines[i].text for i in pos_idx])
            max_negs = max(10, len(pos_idx) * max_neg_multiplier)
            neg_idx = _sample_negatives(len(lines), pos_idx, max_negs)
            negatives.extend([lines[i].text for i in neg_idx])

        total_pos = len(positives)
        total_neg = len(negatives)
        if total_pos < min_pos or total_neg < min_pos:
            report[field] = {"positives": total_pos, "negatives": total_neg, "trained": 0}
            continue

        texts = positives + negatives
        labels = [1] * total_pos + [0] * total_neg

        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1)
        X = vectorizer.fit_transform(texts)
        clf = LogisticRegression(max_iter=1000, class_weight="balanced")
        clf.fit(X, labels)

        payload = {
            "field": field,
            "vectorizer": vectorizer,
            "model": clf,
        }
        model_path = model_dir / f"{field}.joblib"
        joblib.dump(payload, model_path)

        report[field] = {"positives": total_pos, "negatives": total_neg, "trained": 1}

    meta = {
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stats": stats,
        "report": report,
    }
    with open(model_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return report


class MLLinePredictor:
    _cached: Optional["MLLinePredictor"] = None

    def __init__(self, model_dir: Path = MODEL_DIR):
        self.model_dir = model_dir
        self.models: Dict[str, ModelPackage] = {}
        self.stats: Dict[str, Dict[str, float]] = {}
        self._load()

    @classmethod
    def get_cached(cls, model_dir: Path = MODEL_DIR) -> "MLLinePredictor":
        """Переиспользует уже загруженные модели вместо повторного чтения
        ~19 .joblib файлов с диска на каждый PDF."""
        if cls._cached is None or cls._cached.model_dir != model_dir:
            cls._cached = cls(model_dir)
        return cls._cached

    def _load(self) -> None:
        if not self.model_dir.exists():
            return
        meta_path = self.model_dir / "metadata.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                self.stats = meta.get("stats", {})
            except Exception:
                self.stats = {}
        try:
            import joblib
        except Exception:
            return
        for field in FIELD_DEFS.keys():
            model_path = self.model_dir / f"{field}.joblib"
            if not model_path.exists():
                continue
            payload = joblib.load(model_path)
            self.models[field] = ModelPackage(
                field=field,
                vectorizer=payload["vectorizer"],
                model=payload["model"],
            )

    def available(self) -> bool:
        return bool(self.models)

    def extract_from_pdf(self, pdf_path: Path, ocr: bool = False, ocr_pages: Optional[List[int]] = None) -> Tuple[Dict[str, object], Dict[str, float]]:
        extractor = LineExtractor(ocr=ocr, ocr_pages=ocr_pages)
        lines = extractor.extract_lines(pdf_path)
        results: Dict[str, object] = {}
        confidences: Dict[str, float] = {}
        if not lines:
            return results, confidences

        line_texts = [line.text for line in lines]
        sp_table_value = _extract_sp_table_end_from_lines(line_texts)
        if sp_table_value is not None:
            results["sp_table_end"] = sp_table_value
            confidences["sp_table_end"] = 0.95
        for field, pack in self.models.items():
            if field == "sp_table_end" and sp_table_value is not None:
                continue
            X = pack.vectorizer.transform(line_texts)
            probs = pack.model.predict_proba(X)[:, 1]
            if probs.size == 0:
                continue
            best_idx = int(probs.argmax())
            best_prob = float(probs[best_idx])
            line = line_texts[best_idx]
            value = _extract_value_from_line(line, field, self.stats)
            if value is None:
                continue
            results[field] = value
            confidences[field] = best_prob
        return results, confidences


def _extract_sp_table_end_from_lines(lines: List[str]) -> Optional[float]:
    values = []
    pattern = re.compile(r"\bСПО\s*[:=]\s*([0-9OО\s]+[.,][0-9OО]{1,2}|[0-9OО]+)", re.IGNORECASE)
    for line in lines:
        normalized = (
            line.replace("C", "С")
            .replace("P", "Р")
            .replace("c", "с")
            .replace("p", "р")
        )
        match = pattern.search(normalized)
        if not match:
            continue
        value = match.group(1).replace(" ", "").replace(",", ".")
        value = value.replace("O", "0").replace("О", "0")
        try:
            values.append(float(value))
        except Exception:
            continue
    if not values:
        return None
    return max(values)


def _extract_value_from_line(line: str, field: str, stats: Dict[str, Dict[str, float]]) -> Optional[object]:
    ftype = FIELD_DEFS.get(field)
    if not ftype:
        return None
    if ftype == "str":
        if field == "field":
            match = re.search(r"([А-Я][а-я]+ское|[А-Я][а-я]+ное)", line)
            if match:
                return match.group(1)
        return line.strip()
    if field == "sp_table_end":
        match = re.search(r"СПО\\s*[:=]?\\s*([0-9\\s]+[\\.,][0-9]{1,2}|\\d+)", line, re.IGNORECASE)
        if match:
            value = match.group(1).replace(" ", "").replace(",", ".")
            try:
                return float(value)
            except Exception:
                pass
    if ftype == "date":
        match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", line)
        if not match:
            return None
        day, month, year = match.groups()
        if len(year) == 2:
            year = "20" + year
        time_match = re.search(r"(\d{1,2})\D+(\d{2})", line[match.end():])
        hour = "00"
        minute = "00"
        if time_match:
            hour = time_match.group(1).zfill(2)
            minute = time_match.group(2).zfill(2)
        return f"{day.zfill(2)}.{month.zfill(2)}.{year} {hour}:{minute}"

    nums = _numbers_in_line(line)
    if not nums:
        return None

    if ftype == "int":
        if field == "order":
            candidates = [n for n in nums if n >= 100000]
            if candidates:
                return int(round(candidates[0]))
        if field == "well_bush":
            candidates = [n for n in nums if n <= 999]
            if candidates:
                return int(round(candidates[0]))
        return int(round(nums[0]))

    if ftype == "float":
        stat = stats.get(field)
        if stat:
            median = stat.get("median")
            if median is not None:
                nums.sort(key=lambda n: abs(n - median))
                return float(nums[0])
        return float(nums[0])

    return None


def main():
    parser = argparse.ArgumentParser(description="Train ML line models for PDF fields")
    parser.add_argument("--csv", default=str(RAW_CSV_PATH), help="Path to CSV file")
    parser.add_argument("--input", default=str(INPUT_DIR), help="Path to PDF input directory")
    parser.add_argument("--models", default=str(MODEL_DIR), help="Path to models dir")
    parser.add_argument("--ocr", action="store_true", help="Use OCR on pages without text")
    parser.add_argument("--ocr-pages", default="", help="Comma-separated 1-based pages to OCR")
    parser.add_argument("--min-pos", type=int, default=3, help="Minimum positives to train a field")
    args = parser.parse_args()

    ocr_pages = []
    if args.ocr_pages:
        try:
            ocr_pages = [int(p.strip()) for p in args.ocr_pages.split(",") if p.strip().isdigit()]
        except Exception:
            ocr_pages = []

    report = train_models(
        csv_path=Path(args.csv),
        input_dir=Path(args.input),
        model_dir=Path(args.models),
        ocr=args.ocr,
        ocr_pages=ocr_pages,
        min_pos=args.min_pos,
    )
    print("ML обучение завершено")
    for field, info in report.items():
        if info.get("trained"):
            print(f"✅ {field}: +{info['positives']} / -{info['negatives']}")
        else:
            print(f"⚠️ {field}: недостаточно данных (+{info['positives']} / -{info['negatives']})")


if __name__ == "__main__":
    main()
