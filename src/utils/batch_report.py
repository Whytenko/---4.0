from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import List

import openpyxl
import pandas as pd
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

from src.utils.app_paths import ensure_runtime_layout, get_bundled_templates_dir, get_output_dir

# Шаблон с кнопкой-макросом "Перенести в реестр заказчика" (см.
# packaging/excel_macro/README.md) — готовится один раз вручную в
# настоящем Excel, т.к. запрограммировать создание VBA-проекта отсюда
# нельзя (COM-автоматизация Excel.Application на машинах разработки и
# части ПК пользователей перехвачена WPS Office, которая блокирует
# программное создание макросов). Если файла ещё нет — отчёт как и
# раньше строится обычным .xlsx без кнопки, без ошибок.
_TEMPLATE_NAME = "batch_report_template.xlsm"

STATUS_LABELS = {
    "ok": "✅ OK",
    "conditional_ok": "✅ OK (усл.)",
    "bad": "❌ Расхождение",
    "neutral": "— нет данных",
}

# Заливка ячейки по первому символу текста ("✅ OK", "❌ Расхождение",
# "⚠️ МАЛО ДАННЫХ...", "— нет данных") — иконка в тексте легко теряется
# при беглом просмотре десятков строк и колонок, а цвет фона виден сразу.
_FILL_BY_PREFIX = (
    ("❌", PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")),
    ("✅", PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")),
    ("⚠️", PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")),
    ("—", PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")),
)


def _apply_status_fills(worksheet, df: pd.DataFrame) -> None:
    for row_idx, row in enumerate(df.itertuples(index=False), start=2):
        for col_idx, value in enumerate(row, start=1):
            text = str(value)
            for prefix, fill in _FILL_BY_PREFIX:
                if text.startswith(prefix):
                    worksheet.cell(row=row_idx, column=col_idx).fill = fill
                    break

# Статусы, которые считаются "пройдено" при подсчёте общего итога по акту.
_PASSING_STATUSES = {"ok", "conditional_ok"}


def _label(status: str) -> str:
    return STATUS_LABELS.get(status, "— нет данных")


def _label_km(km_status: dict) -> str:
    """Как _label(), но с подробностями (акт/отчёт по каждой категории
    переезда) — иначе ячейка "✅ OK" не даёт понять, какие именно цифры
    сверялись и с каким значением справочника совпали."""
    label = _label(km_status.get("status"))
    details = km_status.get("details") or []
    if not details:
        return label
    compact = "; ".join(line.strip() for line in details)
    return f"{label}: {compact}"


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
    for well_data in wells_data:
        # temperature/km теперь входят в тот же реестр проверок WellData
        # (main_parser._check_temperature/_check_km), что и остальные —
        # единый расчёт что для одиночной проверки акта, что для пакетного
        # отчёта, вместо отдельного дублирующего вызова table_parser/
        # km_parser здесь же.
        checks = well_data.get_check_summary()
        temp_status = checks["temperature"]
        km_status = checks["km"]

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
            checks["interval_length"]["status"],
            checks["spo_zakaz"]["status"],
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
                "Интервал ≤100м (стр.1)": _label(checks["interval_length"]["status"]),
                "СПО (акт-наряд vs акт-заказ)": _label(checks["spo_zakaz"]["status"]),
                "Сверка с заявкой": _label(checks["zayavka"]["status"]),
                "Температура": _label(temp_status["status"]),
                "Километраж": _label_km(km_status),
                "ИТОГ": _row_overall(statuses),
            }
        )

    df = pd.DataFrame(rows)
    registry_df = _build_registry_df(wells_data)

    output_dir = get_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    template_path = get_bundled_templates_dir() / _TEMPLATE_NAME
    if template_path.exists():
        report_path = output_dir / f"Отчет по пакету актов {timestamp}.xlsm"
        shutil.copy2(template_path, report_path)

        wb = openpyxl.load_workbook(report_path, keep_vba=True)
        _write_dataframe(wb["Реестр"], registry_df)
        _autosize_columns(wb["Реестр"], registry_df)

        _write_dataframe(wb["Сводка"], df)
        _autosize_columns(wb["Сводка"], df)
        _apply_status_fills(wb["Сводка"], df)

        wb.save(report_path)
        return report_path

    report_path = output_dir / f"Отчет по пакету актов {timestamp}.xlsx"
    with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
        registry_df.to_excel(writer, index=False, sheet_name="Реестр")
        _autosize_columns(writer.sheets["Реестр"], registry_df)

        df.to_excel(writer, index=False, sheet_name="Сводка")
        _autosize_columns(writer.sheets["Сводка"], df)
        _apply_status_fills(writer.sheets["Сводка"], df)

    return report_path


def _write_dataframe(worksheet, df: pd.DataFrame) -> None:
    """Как df.to_excel(), но через openpyxl на уже существующий лист
    шаблона (.xlsm) — только значения ячеек, не трогая лежащие на том же
    листе объекты (кнопку-макрос), которые pandas.to_excel просто
    уничтожил бы, пересоздав лист с нуля."""
    if worksheet.max_row:
        worksheet.delete_rows(1, worksheet.max_row)
    worksheet.append(list(df.columns))
    for row in df.itertuples(index=False):
        worksheet.append(list(row))


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
                # matched_zayavka_task — если заявка пришла отдельным файлом
                # пакета; embedded_zayavka_task — распознанный (часто через
                # OCR, надёжность ограничена) номер со встроенной страницы
                # заявки; performed_tasks — сама задача из шапки акта, самый
                # надёжный источник (не требует OCR). В реальном реестре
                # заказчика "Заявка" почти всегда совпадает с "Проведенный
                # ГИС" (заявка запрашивает именно ту задачу, что потом
                # выполняется и фиксируется в акте), поэтому это последний
                # и основной запасной вариант, а не безусловный OCR-приоритет.
                "Заявка": (
                    well_data.matched_zayavka_task
                    or well_data.embedded_zayavka_task
                    or well_data.performed_tasks
                ),
                # Свободный комментарий подрядчика (недоход, остановка
                # прибора, осмотр перфоратора и т.д.) со страницы "АКТ" —
                # см. _parse_zayavka_and_comment. Пусто, если такой
                # страницы в акте нет (обычный, без замечаний акт).
                "Комментарии": well_data.contractor_comment,
            }
        )
    return pd.DataFrame(rows)


def _to_number(value: str):
    try:
        return float(value)
    except (TypeError, ValueError):
        return ""
