"""
СПО (спуск/подъём скважинного прибора) по трём источникам: строка
"С/п скв.приб..." на титуле (расц. 346/348), та же расценка в таблице
"Спуски / подъемы" акт-заказа (стр.2) и итог "СПО: ... м" справки по
зарегистрированному материалу. Реальный пример — акт 12490 (задача 54.1):
титул 189,72, акт-заказ (скан) 189,72, справка "СПО: 7279.99 м".
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.extractors.main_parser import FinalUnifiedParser, WellData

_parser = FinalUnifiedParser()

_ROWS_12490 = [
    {"name": "С/п скв.приб. в откр.стволе или кол.", "rate_number": "346", "volume": 189.72},
    {"name": "Услуги партий по обслуживанию действующих скважин", "rate_number": "5", "volume": 1.0},
]


def _well(**overrides):
    base = dict(
        filename="x.pdf", field="Ватьеганское", order="1081516", depth="2100", angle="20",
        temperature="0", volume="", spo="", vm_task="", vm_price="", vm_count="",
        vm_total="", vm_table_count="", volume_sum_page1="", qty_sum_page3="",
        page2_start="", page2_end="", start_date="15.08.2026 09:55", end_date="15.08.2026 19:00",
    )
    base.update(overrides)
    return WellData(**base)


def test_tool_trip_rows_346_and_348():
    assert WellData._tool_trip_volumes(_ROWS_12490) == {"346": 189.72}
    rows = [{"name": "С/п скв.приб. ч/р лубрикатор", "rate_number": "348", "volume": 60.04},
            {"name": "С/п шаблона в отк.стволе или кол.", "rate_number": "357", "volume": 62.0}]
    assert WellData._tool_trip_volumes(rows) == {"348": 60.04}


def test_zakaz_scan_matches_title():
    well = _well()
    well.page2_spo, well.page2_spo_rate, well.page2_spo_from_ocr = "189,72", "346", True
    assert well._check_spo_zakaz(_ROWS_12490)["status"] == "ok"
    # OCR потерял запятую — те же цифры, совпадение.
    well.page2_spo = "18972"
    assert well._check_spo_zakaz(_ROWS_12490)["status"] == "ok"


def test_zakaz_scan_other_digits_is_warning_not_mismatch():
    # Акт 12271: на скане 200,32, OCR прочитал "20052" — не ❌, а ⚠.
    well = _well()
    rows = [{"name": "С/п скв.приб. ч/р лубрикатор", "rate_number": "348", "volume": 200.32}]
    well.page2_spo, well.page2_spo_rate, well.page2_spo_from_ocr = "20052", "348", True
    result = well._check_spo_zakaz(rows)
    assert result["status"] == "conditional_ok"
    # Совпал хотя бы один вариант прочтения — ✅.
    well.page2_spo_candidates = ["20052", "200,32"]
    assert well._check_spo_zakaz(rows)["status"] == "ok"


def test_zakaz_text_layer_mismatch_is_bad():
    well = _well()
    well.page2_spo, well.page2_spo_rate, well.page2_spo_from_ocr = "180.00", "346", False
    assert well._check_spo_zakaz(_ROWS_12490)["status"] == "bad"


def test_zakaz_not_recognised_is_neutral():
    result = _well()._check_spo_zakaz(_ROWS_12490)
    assert result["status"] == "neutral"
    assert "не распознан" in result["value_text"]


def test_reference_spo_strict_format():
    # Итог справки — с двоеточием и дробной частью.
    assert _parser._parse_spo_from_text("Стр. 1 из 1\nСПО: 7279.99 м\n") == "7279.99"
    assert _parser._parse_spo_from_text("Спуск-подъём прибора составил – 1135.30 м") == "1135.30"
    assert _parser._parse_spo_from_text("СПО: 100 м") == "100"  # акт 12676
    # Посторонние "СПО" на других листах больше не подхватываются.
    assert _parser._parse_spo_from_text("Условия проведения СПО 4") == ""
    assert _parser._parse_spo_from_text("2 СПО1 магнитного ловителя 0-1820 11:00-12:10") == ""


def test_reference_mismatch_is_warning_for_tasks_outside_instruction():
    # Акт 12490, задача 54.1: справка относится к другой работе (шаблон,
    # задача 053) — по инструкции СПО по справке проверяется только у
    # задач 53, 11, 34, 35, 6, 7, 80, 87.
    well = _well(volume="189,72", spo="7279.99")
    well.performed_tasks = "54.1"
    assert well._check_volume_spo()["status"] == "conditional_ok"
    well.performed_tasks = "35(S)"
    assert well._check_volume_spo()["status"] == "bad"
    well = _well(volume="72,79", spo="7279.99")
    well.performed_tasks = "53"
    assert well._check_volume_spo()["status"] == "ok"
