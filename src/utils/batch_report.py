from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd
from openpyxl.utils import get_column_letter

from src.utils.app_paths import ensure_runtime_layout, get_output_dir
from src.extractors import km_parser, table_parser

STATUS_LABELS = {
    "ok": "✅ OK",
    "conditional_ok": "✅ OK (усл.)",
    "bad": "❌ Расхождение",
    "neutral": "— нет данных",
}

# Статусы, которые считаются "пройдено" при подсчёте общего итога по акту.
_PASSING_STATUSES = {"ok", "conditional_ok"}


def _label(status: str) -> str:
    return STATUS_LABELS.get(status, "— нет данных")


def _row_overall(statuses: List[str]) -> str:
    if any(status == "bad" for status in statuses):
        return "❌ ЕСТЬ РАСХОЖДЕНИЯ"
    checked = sum(1 for status in statuses if status in _PASSING_STATUSES)
    if checked == 0:
        return "— нет данных"
    # Если реально проверенного (не "нет данных") меньше трети — "ВСЕ ОК"
    # было бы обманчиво: почти ничего не сверялось, просто нечего было
    # проверять (не найдены нужные поля/справочники).
    if checked < max(2, len(statuses) // 3):
        return "⚠️ МАЛО ДАННЫХ ДЛЯ ПРОВЕРКИ"
    return "✅ ВСЕ ОК"


def build_batch_report(pdf_paths: List[Path], wells_data: List) -> Path:
    """Строит сводный Excel-отчёт по уже обработанному пакету актов.

    Принимает pdf_paths и уже посчитанный wells_data (из PDFProcessor) —
    сам по себе не открывает и не парсит PDF заново.
    """
    ensure_runtime_layout(copy_reference=True)

    rows = []
    for pdf_path, well_data in zip(pdf_paths, wells_data):
        pdf_path = Path(pdf_path)
        checks = well_data.get_check_summary()
        temp_status = table_parser.get_temperature_status(well_data)
        try:
            km_status = km_parser.compute_km_report(pdf_path)
        except Exception:
            km_status = {"status": "neutral"}

        statuses = [
            checks["spo"]["status"],
            checks["vm_cost"]["status"],
            checks["rate"]["status"],
            checks["volume_qty"]["status"],
            checks["page2_dates"]["status"],
            checks["contract_number_page2"]["status"],
            checks["integral"]["status"],
            checks["contract_coeff"]["status"],
            checks["barometry_task53"]["status"],
            checks["tech_duty"]["status"],
            checks["thermometry_overlap"]["status"],
            checks["zayavka"]["status"],
            temp_status["status"],
            km_status["status"],
        ]

        rows.append(
            {
                "Файл": well_data.filename,
                "Месторождение": well_data.field,
                "Номер заказа": well_data.order,
                "Номер задачи": well_data.task_number,
                "Куст": well_data.bush,
                "Скважина": well_data.well_number,
                "Начало работ": well_data.start_date,
                "Окончание работ": well_data.end_date,
                "СПО": _label(checks["spo"]["status"]),
                "Цена ВМ": _label(checks["vm_cost"]["status"]),
                "Расценки": _label(checks["rate"]["status"]),
                "Объёмы/кол-во": _label(checks["volume_qty"]["status"]),
                "Даты (стр.2)": _label(checks["page2_dates"]["status"]),
                "Номер договора (стр.2)": _label(checks["contract_number_page2"]["status"]),
                "Интеграл. коэфф.": _label(checks["integral"]["status"]),
                "Коэфф. по договору": _label(checks["contract_coeff"]["status"]),
                "Барометрия@53": _label(checks["barometry_task53"]["status"]),
                "Тех.дежурство >4ч": _label(checks["tech_duty"]["status"]),
                "Термометрия 200/500": _label(checks["thermometry_overlap"]["status"]),
                "Сверка с заявкой": _label(checks["zayavka"]["status"]),
                "Температура": _label(temp_status["status"]),
                "Километраж": _label(km_status["status"]),
                "ИТОГ": _row_overall(statuses),
            }
        )

    df = pd.DataFrame(rows)
    registry_df = _build_registry_df(wells_data)

    output_dir = get_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_path = output_dir / f"Отчет по пакету актов {timestamp}.xlsx"

    with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
        registry_df.to_excel(writer, index=False, sheet_name="Реестр")
        _autosize_columns(writer.sheets["Реестр"], registry_df)

        df.to_excel(writer, index=False, sheet_name="Сводка")
        _autosize_columns(writer.sheets["Сводка"], df)

    return report_path


def _autosize_columns(worksheet, df: pd.DataFrame) -> None:
    for col_idx, col_name in enumerate(df.columns, start=1):
        max_len = max([len(str(col_name))] + [len(str(v)) for v in df[col_name].astype(str)])
        worksheet.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 4, 45)
    worksheet.freeze_panes = "A2"


def _build_registry_df(wells_data: List) -> pd.DataFrame:
    """Реестр в формате заказчика ("Проверка акт-нарядов ГГГГ.xlsx"):
    № Договора / № Заказа / Месторождение / Скважина / Куст / № Акт-Наряда /
    Дата предоставления / Окончание работ / Стоимость / Проведенный ГИС /
    Заявка / Комментарии. Второй "№ п/п" — порядковый номер внутри одной
    "Дата предоставления" (сбрасывается на 1 при смене даты) — так же, как
    в реестре заказчика, где акты группируются по дню поступления."""
    rows = []
    seen_per_date: dict = {}
    for well_data in wells_data:
        act_date = well_data.act_date or ""
        seen_per_date[act_date] = seen_per_date.get(act_date, 0) + 1
        rows.append(
            {
                "№ п/п": len(rows) + 1,
                "№ п/п ": seen_per_date[act_date],
                "№ Договора": well_data.contract_number_display,
                "№ Заказа": well_data.order,
                "Месторождение": well_data.field,
                "Скважина": well_data.well_number,
                "Куст": well_data.bush,
                "№ Акт-Наряда": well_data.act_number,
                "Дата предоставления": act_date,
                "Окончание работ": well_data.end_date,
                "Стоимость": _to_number(well_data.total_cost),
                "Проведенный ГИС": well_data.performed_tasks,
                "Заявка": well_data.matched_zayavka_task,
                "Комментарии": "",
            }
        )
    return pd.DataFrame(rows)


def _to_number(value: str):
    try:
        return float(value)
    except (TypeError, ValueError):
        return ""
