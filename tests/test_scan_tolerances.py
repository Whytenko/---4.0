"""
Регрессионные тесты: ложные расхождения из-за масштаба СПО и рукописных
сканов, пустой угол наклона, соответствие имени файла содержимому акта.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.extractors.main_parser import FinalUnifiedParser, WellData

_parser = FinalUnifiedParser()


def _well(**overrides):
    base = dict(
        filename="x.pdf", field="Повховское", order="1", depth="2500", angle="36,5",
        temperature="0", volume="", spo="", vm_task="", vm_price="", vm_count="",
        vm_total="", vm_table_count="", volume_sum_page1="", qty_sum_page3="",
        page2_start="", page2_end="", start_date="17.08.2026 06:00", end_date="17.08.2026 11:00",
    )
    base.update(overrides)
    return WellData(**base)


def test_short_spo_is_scaled_to_metres():
    # Акт 12486 (задача 24): на титуле 0,23 (сотни метров), в справке 23,20 м.
    assert _well(volume="0,23", spo="23.20")._check_volume_spo()["status"] == "ok"
    # Акт 12682: 8,50 против 853,14 м — три метра разницы остаются расхождением.
    assert _well(volume="8,50", spo="853.14")._check_volume_spo()["status"] == "bad"


def test_unreadable_spo_reference_is_not_a_mismatch():
    # Акт 12490: спуск 18 972 м, из справки прочитано "4,00".
    assert _well(volume="189,72", spo="4.00")._check_volume_spo()["status"] == "neutral"


def test_scanned_time_mismatch_is_conditional():
    # Акт 12559: даты совпали, время со скана OCR прочитал неверно.
    well = _well(page2_start="17.08.2026 06:34", page2_end="17.08.2026 00:00")
    well.page2_dates_from_ocr = True
    assert well._check_page2_dates()["status"] == "conditional_ok"
    # Тот же случай на акт-заказе с текстовым слоем — настоящее расхождение.
    well.page2_dates_from_ocr = False
    assert well._check_page2_dates()["status"] == "bad"
    # Другой день и на скане остаётся расхождением.
    well = _well(page2_start="16.08.2026 06:00", page2_end="17.08.2026 11:00")
    well.page2_dates_from_ocr = True
    assert well._check_page2_dates()["status"] == "bad"


def test_missing_angle_is_reported_in_integral_check():
    # Акт 13059: поле "Угол наклона" на титуле пустое.
    rows = [
        {"name": "Запись муфтовых соед.локатором муфт (ЛМ)", "integral_coeff": 1.15},
        {"name": "Переезд комп.партии в действ.фонде,1 гр.дорог", "integral_coeff": 1.00},
    ]
    status, details = _parser._check_integral_rows(rows, "0", "не найдено")
    assert status == "ok"
    assert any("Угол наклона в акте не указан" in line for line in details)


def test_filename_matches_act():
    well = _well(filename="16003_им. В.И. Некрасова (Южно-Выинтойское) _29_1052Г_35(S)_1085468.pdf", order="1085468")
    well.act_number, well.well_number, well.bush, well.performed_tasks = "16003", "1052Г", "29", "35(S)"
    assert well._check_filename()["status"] == "ok"
    well.order = "1085469"
    result = well._check_filename()
    assert result["status"] == "bad" and "Заказ" in result["details"][0]
    # "пересчет" в конце имени и ведущие нули в номере акта — не ошибка.
    well = _well(filename="05883_Повховское_84Б_3221_61_1072285 пересчет.pdf", order="1072285")
    well.act_number, well.well_number, well.bush, well.performed_tasks = "5883", "3221", "84Б", "61"
    assert well._check_filename()["status"] == "ok"
    # Имя не по шаблону — проверка не выполняется.
    well.filename = "акт.pdf"
    assert well._check_filename()["status"] == "neutral"
