import re
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
import sys

SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from .main_parser import FinalUnifiedParser
except Exception:
    from main_parser import FinalUnifiedParser

from src.utils.app_paths import ensure_runtime_layout, get_input_dir, get_reference_dir

MONTH_NAMES = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}

def _pick_sheet_candidates(sheet_names, month_name, year):
    year_suffix = str(year)[-2:]
    target = f"{month_name}{year_suffix}"

    normalized = {name: name.replace(" ", "") for name in sheet_names}
    year_candidates = [
        name for name, norm in normalized.items()
        if norm == target
    ]
    candidates = []
    # Prefer base month sheet first to avoid stale/incorrect year tabs.
    for name in sheet_names:
        if name.strip() == month_name:
            candidates.append(name)
            break
    if year_candidates and year_candidates[0] not in candidates:
        candidates.append(year_candidates[0])
    return candidates

# Кэши, чтобы не перечитывать один и тот же Excel-файл/лист с диска на
# каждый час продолжительности акта (get_table_data вызывается по разу на
# каждый час работ — на длинном акте это десятки повторных чтений).
_SHEET_NAMES_CACHE: dict[str, list] = {}
_SHEET_DF_CACHE: dict[tuple[str, str], "pd.DataFrame"] = {}


def _resolve_temperature_excel_path(ref_dir: Path, year: int) -> Path:
    year_path = ref_dir / f"20. Отчет по температуре {year}.xlsx"
    if year_path.exists():
        return year_path

    plain_path = ref_dir / "20. Отчет по температуре.xlsx"
    if plain_path.exists():
        return plain_path

    # Резервный поиск по маске — намеренно исключаем годовые файлы других
    # лет из кандидатов для года year, чтобы не сравнить акт с чужой
    # температурной таблицей.
    candidates = sorted(ref_dir.glob("20. Отчет по температуре*.xlsx"))
    year_candidates = [c for c in candidates if str(year) in c.stem]
    if year_candidates:
        return year_candidates[0]
    non_year_candidates = [c for c in candidates if not re.search(r'20\d{2}', c.stem)]
    if non_year_candidates:
        return non_year_candidates[0]
    if candidates:
        return candidates[0]
    return plain_path


def get_table_data(dt, well_type):
    """
    Получает данные из таблицы с ПРАВИЛЬНОЙ логикой
    """
    hour = dt.hour
    lookup_dt = dt
    if hour in (0, 1, 2):
        # 00:00, 01:00, 02:00 относятся к 24:00/02:00 предыдущего дня
        lookup_dt = dt - timedelta(days=1)
    day = lookup_dt.day
    month = lookup_dt.month

    ref_dir = get_reference_dir()
    excel_path = _resolve_temperature_excel_path(ref_dir, dt.year)

    month_name = MONTH_NAMES.get(month)
    if not month_name:
        return None

    try:
        path_key = str(excel_path)
        sheet_names = _SHEET_NAMES_CACHE.get(path_key)
        if sheet_names is None:
            sheet_names = pd.ExcelFile(excel_path).sheet_names
            _SHEET_NAMES_CACHE[path_key] = sheet_names

        sheet_candidates = _pick_sheet_candidates(sheet_names, month_name, dt.year)
        if not sheet_candidates:
            return None

        for sheet_name in sheet_candidates:
            cache_key = (path_key, sheet_name)
            df = _SHEET_DF_CACHE.get(cache_key)
            if df is None:
                df = pd.read_excel(excel_path, sheet_name=sheet_name, header=None)
                _SHEET_DF_CACHE[cache_key] = df

            # 1. Находим таблицу ВАТЬЕГАН или ПОВХ
            start_row = None
            for i in range(df.shape[0]):
                cell = str(df.iloc[i, 0])
                if well_type in cell:
                    start_row = i
                    break

            if start_row is None:
                continue

            # 2. Находим начало данных (через 2 строки)
            data_start = start_row + 2

            # 3. Находим БЛИЖАЙШЕЕ время в таблице
            # Часы в таблице: 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 2
            table_hours = [4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 2]

            # Если час 0 - это 24, если 1-2 часа - используем 2 (ближайшее значение в таблице)
            if hour == 0:
                search_hour = 24
            elif hour in (1, 2):
                search_hour = 2
            else:
                search_hour = hour

            # Находим ближайший час
            closest_hour = min(table_hours, key=lambda x: abs(x - search_hour))

            # 4. Определяем день в таблице
            # ОСОБЕННОСТЬ: 00:00 30 ноября -> это данные дня 30 в таблице!
            # 02:00 30 ноября -> это тоже данные дня 30 в таблице!
            table_day = day  # По умолчанию тот же день

            # 5. Находим строку с нужным временем
            time_row = None
            for i in range(data_start, min(data_start + 15, df.shape[0])):
                time_cell = str(df.iloc[i, 0]).strip()
                try:
                    cell_hour = float(time_cell.replace(',', '.'))
                    if abs(cell_hour - closest_hour) < 0.1:
                        time_row = i
                        break
                except Exception:
                    continue

            if time_row is None:
                continue

            # 6. Определяем колонку дня
            # В Excel: колонка 0 = "Время", колонка 1 = день 1, колонка 2 = день 2
            excel_col = table_day  # день 30 -> колонка 30

            if excel_col >= df.shape[1]:
                continue

            # 7. Получаем значение
            value = df.iloc[time_row, excel_col]

            if pd.isna(value):
                continue

            # 8. Преобразуем в число
            try:
                temp = float(str(value).replace(',', '.'))
                return temp
            except Exception:
                continue

        return None
            
    except Exception as e:
        print(f"Ошибка: {e}")
        return None

def _parse_float(value):
    if value is None:
        return None
    try:
        return float(str(value).replace(',', '.'))
    except Exception:
        return None

def _compute_temp_stats(well_type, start_dt, end_dt, pdf_temp):
    temps = []
    current_dt = start_dt

    while current_dt <= end_dt:
        temp = get_table_data(current_dt, well_type)
        if temp is not None:
            temps.append(temp)
        current_dt += timedelta(hours=1)

    if not temps:
        return {"status": "neutral", "reason": "no_table_data"}

    avg_temp = sum(temps) / len(temps)
    if pdf_temp is None:
        return {"status": "neutral", "reason": "no_pdf_temp", "avg_temp": avg_temp}

    diff = abs(pdf_temp - avg_temp)
    match = diff <= 5.0
    return {"status": "ok" if match else "bad", "avg_temp": avg_temp, "pdf_temp": pdf_temp, "diff": diff}


def analyze_period(well_name, well_type, start_dt, end_dt, pdf_temp):
    result = _compute_temp_stats(well_type, start_dt, end_dt, pdf_temp)

    print(f"\nОтчет по температуре: {well_name}")
    if result["status"] == "neutral" and result.get("reason") == "no_table_data":
        print("Нет данных для анализа")
        return
    if result["status"] == "neutral" and result.get("reason") == "no_pdf_temp":
        print("Температура в акте: не найдена")
        return

    print(f"Средняя температура: {result['avg_temp']:.2f}°C")
    print(f"Температура в акте: {result['pdf_temp']:.2f}°C")
    print(f"Разница: {result['diff']:.2f}°C")
    print(f"📋 РЕЗУЛЬТАТ: ", end="")
    if result["status"] == "ok":
        print("✅ СООТВЕТСТВУЕТ (±5°C)")
    else:
        print("❌ НЕ СООТВЕТСТВУЕТ")


def _derive_well_type(field: str) -> str:
    """Опорное слово для поиска раздела месторождения в '21. Отчет по
    температуре' — берём корень названия месторождения (без типового
    русского окончания), в верхнем регистре, как в заголовках таблицы
    (ВАТЬЕГАН, ПОВХ...). Работает для любого месторождения, не только для
    двух захардкоженных ранее."""
    field = (field or "").strip()
    if not field:
        return ""
    root = re.sub(r'(ское|цкое|ное|ный|ая)$', '', field, flags=re.IGNORECASE)
    return root.upper()


def get_temperature_status(well_data) -> dict:
    """Структурированный статус температурной проверки без печати
    (используется для пакетного Excel-отчёта)."""
    well_type = _derive_well_type(well_data.field)
    if not well_type:
        return {"status": "neutral", "reason": "unknown_field"}

    try:
        start_dt = datetime.strptime(well_data.start_date, "%d.%m.%Y %H:%M")
        end_dt = datetime.strptime(well_data.end_date, "%d.%m.%Y %H:%M")
    except Exception:
        return {"status": "neutral", "reason": "bad_dates"}

    pdf_temp = _parse_float(well_data.temperature)
    return _compute_temp_stats(well_type, start_dt, end_dt, pdf_temp)

def analyze_well_data(well_data, pdf_name: str):
    well_type = _derive_well_type(well_data.field)
    if not well_type:
        print(f"❌ Не удалось определить месторождение: {well_data.field}")
        return

    try:
        start_dt = datetime.strptime(well_data.start_date, "%d.%m.%Y %H:%M")
        end_dt = datetime.strptime(well_data.end_date, "%d.%m.%Y %H:%M")
    except Exception:
        print(f"❌ Не удалось распарсить даты: {well_data.start_date} - {well_data.end_date}")
        return

    pdf_temp = _parse_float(well_data.temperature)
    analyze_period(pdf_name, well_type, start_dt, end_dt, pdf_temp)


def analyze_from_pdf(pdf_path: Path):
    parser = FinalUnifiedParser()
    well_data = parser.parse_all(str(pdf_path))
    analyze_well_data(well_data, pdf_path.name)


def run_report(pdf_paths, wells_data):
    """Строит отчёт по температуре из уже посчитанных WellData
    (из main_parser), не открывая и не распознавая PDF заново."""
    ensure_runtime_layout(copy_reference=True)
    by_name = {getattr(wd, "filename", None): wd for wd in wells_data}
    for pdf_path in pdf_paths:
        pdf_path = Path(pdf_path)
        well_data = by_name.get(pdf_path.name)
        if well_data is None:
            analyze_from_pdf(pdf_path)
            continue
        analyze_well_data(well_data, pdf_path.name)

def main(args=None):
    ensure_runtime_layout(copy_reference=True)
    cli_args = args if args is not None else sys.argv[1:]
    input_dir = get_input_dir()
    if cli_args:
        for arg in cli_args:
            candidate = Path(arg)
            if not candidate.is_absolute():
                candidate = input_dir / arg
            if not candidate.exists():
                print(f"❌ Файл не найден: {candidate}")
                continue
            analyze_from_pdf(candidate)
        return

    pdf_files = list(input_dir.glob("*.pdf"))
    if not pdf_files:
        print("❌ Файлы не найдены")
        return
    for pdf_file in pdf_files:
        analyze_from_pdf(pdf_file)


if __name__ == "__main__":
    main()
