from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

import pdfplumber

# Порядок значим: заявка/акт-на-простой распознаются по достаточно
# специфичным маркерам; всё остальное по умолчанию считается акт-нарядом
# (как и раньше, до появления пакетной проверки) — чтобы неопознанный формат
# не выпадал из обработки, а просто парсился как акт (с "не найдено" в полях,
# как это уже было).


def classify_pdf(pdf_path: Path) -> tuple[str, str]:
    """Возвращает (тип, текст 1 страницы). Тип: 'zayavka' | 'akt_prostoy' | 'akt_naryad'."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = pdf.pages[0].extract_text() if pdf.pages else ""
    except Exception:
        return "akt_naryad", ""

    text = text or ""
    stripped = text.strip()
    upper = stripped.upper()

    if upper.startswith("ЗАЯВКА") or re.search(r'ЗАЯВКА\s*№', upper):
        return "zayavka", text

    # Требуем целую фразу "акт на простой", а не совпадение отдельных
    # обрывков слов — иначе ложно срабатывает на словах вроде "пространстве"
    # (подстрока "прост"), которые обычны в обычных актах-нарядах.
    if re.search(r'акт\s+на\s+прост', upper, re.IGNORECASE):
        return "akt_prostoy", text

    return "akt_naryad", text


def parse_zayavka_text(text: str) -> dict:
    return {
        "order": _parse_order_number(text),
        "field": _parse_field(text),
        "bush": _parse_bush(text),
        "well": _parse_well_number(text),
        "task": _parse_task_number(text),
    }


def _parse_order_number(text: str) -> str:
    match = re.search(
        r'№\s*Заявки\s*\(?Акт[\s\-]*Заказа\)?\s*[:\.]?\s*([0-9]{6,7})', text, re.IGNORECASE
    )
    if match:
        return match.group(1)
    match = re.search(r'Заказ\s*№[^\d]*([0-9]{6,7})', text)
    return match.group(1) if match else ""


def _parse_field(text: str) -> str:
    keyword = re.search(r'площадь|месторождение', text, re.IGNORECASE)
    if not keyword:
        return ""
    tail = text[keyword.end():keyword.end() + 80]
    match = re.search(r'([А-Я][а-я]+ское|[А-Я][а-я]+ное)', tail)
    return match.group(1) if match else ""


def _parse_bush(text: str) -> str:
    match = re.search(r'куст\w*\s*№?\s*([0-9]+)', text, re.IGNORECASE)
    return match.group(1) if match else ""


def _parse_well_number(text: str) -> str:
    match = re.search(r'скважин\w*\s*№\s*([0-9]+)', text, re.IGNORECASE)
    return match.group(1) if match else ""


def _parse_task_number(text: str) -> str:
    match = re.search(r'Задача\s*№?\s*([0-9]+(?:\.[0-9]+)?)', text)
    return match.group(1) if match else ""


def load_zayavka(pdf_path: Path) -> Optional[dict]:
    kind, text = classify_pdf(pdf_path)
    if kind != "zayavka":
        return None
    data = parse_zayavka_text(text)
    data["filename"] = pdf_path.name
    return data


def _fields_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return a.strip().lower() == b.strip().lower()


def match_zayavka_for_well(well_data, zayavki: List[dict]) -> Optional[dict]:
    """Сопоставление приоритетно по номеру заказа (как в акте), если он
    распознан как текст в заявке; иначе — по месторождению+кусту+скважине."""
    order = str(getattr(well_data, "order", "") or "").strip()
    if order and order != "не найдено":
        for z in zayavki:
            if z.get("order") and z["order"] == order:
                return z

    field = getattr(well_data, "field", "") or ""
    bush = str(getattr(well_data, "bush", "") or "").strip()
    well_number = str(getattr(well_data, "well_number", "") or "").strip()
    if bush and well_number:
        for z in zayavki:
            if (
                z.get("bush") == bush
                and z.get("well") == well_number
                and (not z.get("field") or _fields_match(field, z["field"]))
            ):
                return z

    return None


def check_against_zayavka(well_data, zayavka: Optional[dict]) -> dict:
    if zayavka is None:
        return {"status": "neutral"}

    mismatches: List[str] = []

    field = getattr(well_data, "field", "") or ""
    if zayavka.get("field") and field and not _fields_match(field, zayavka["field"]):
        mismatches.append(f"Месторождение: акт={field} / заявка={zayavka['field']}")

    bush = str(getattr(well_data, "bush", "") or "").strip()
    if zayavka.get("bush") and bush and zayavka["bush"] != bush:
        mismatches.append(f"Куст: акт={bush} / заявка={zayavka['bush']}")

    well_number = str(getattr(well_data, "well_number", "") or "").strip()
    if zayavka.get("well") and well_number and zayavka["well"] != well_number:
        mismatches.append(f"Скважина: акт={well_number} / заявка={zayavka['well']}")

    act_task = str(getattr(well_data, "task_number", "") or "").strip()
    zay_task = str(zayavka.get("task") or "").strip()

    note = ""
    if act_task.startswith("500.4"):
        # Недоход: по инструкции — если по заявке (58) получен недоход,
        # в акте должна стоять задача 500.4. Это ожидаемое несовпадение,
        # а не ошибка.
        note = f"Недоход: заявка на задачу №{zay_task or '?'}, в акте — 500.4 (ожидаемо)"
    elif zay_task and act_task and zay_task != act_task:
        mismatches.append(f"Номер задачи: акт={act_task} / заявка={zay_task}")

    status = "bad" if mismatches else "ok"
    details = list(mismatches)
    if note:
        details.append(note)
    if not details:
        details = [f"Совпадает с заявкой: {zayavka.get('filename', '')}"]

    return {"status": status, "details": details, "matched_zayavka": zayavka.get("filename")}


def apply_zayavka_checks(wells_data: List, zayavki: List[dict]) -> None:
    """Сопоставляет и проставляет статус/детали прямо на WellData."""
    if not zayavki:
        return
    for well_data in wells_data:
        match = match_zayavka_for_well(well_data, zayavki)
        result = check_against_zayavka(well_data, match)
        well_data.zayavka_check_status = result["status"]
        well_data.zayavka_check_details = result.get("details", [])
