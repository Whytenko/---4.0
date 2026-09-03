"""
Регрессионные тесты для более простых точечных проверок: коэффициент по
договору, барометрия при задаче 53, тех.дежурство >4ч, пересечение
термометрии 200/500, исключение "переезд на другой объект" в километраже.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.extractors.main_parser import WellData
from src.extractors import km_parser


def _make_well_data(**overrides):
    base = dict(
        filename="x.pdf", field="Ватьеганское", order="1", depth="2500", angle="36,5",
        temperature="0", volume="", spo="", vm_task="", vm_price="", vm_count="",
        vm_total="", vm_table_count="", volume_sum_page1="", qty_sum_page3="",
        page2_start="", page2_end="", start_date="01.12.2025 08:00", end_date="02.12.2025 08:00",
    )
    base.update(overrides)
    return WellData(**base)


# ---- Коэффициент по договору ----

def test_contract_coefficient_match():
    well = _make_well_data()
    well.contract_number = "2026008065"
    well.contract_coeff_value = 1.330
    result = well._check_contract_coefficient()
    assert result["status"] == "ok"


def test_contract_coefficient_mismatch():
    well = _make_well_data()
    well.contract_number = "2026008065"
    well.contract_coeff_value = 1.500
    result = well._check_contract_coefficient()
    assert result["status"] == "bad"


def test_contract_coefficient_unknown_contract_is_neutral():
    well = _make_well_data()
    well.contract_number = "22С3286"  # не в справочнике (старый формат номера)
    well.contract_coeff_value = 1.147
    result = well._check_contract_coefficient()
    assert result["status"] == "neutral"


# ---- Барометрия при задаче 53 ----

def test_barometry_task53_present():
    well = _make_well_data()
    well.task_number = "53"
    rows = [{"name": "Барометрия скв.  Запись точечная"}]
    assert well._check_barometry_task53(rows)["status"] == "ok"


def test_barometry_task53_missing():
    well = _make_well_data()
    well.task_number = "53"
    rows = [{"name": "Запись муфтовых соед.локатором муфт (ЛМ)"}]
    assert well._check_barometry_task53(rows)["status"] == "bad"


def test_barometry_check_neutral_for_other_tasks():
    well = _make_well_data()
    well.task_number = "58.141"
    rows = [{"name": "Запись муфтовых соед.локатором муфт (ЛМ)"}]
    assert well._check_barometry_task53(rows)["status"] == "neutral"


# ---- Тех.дежурство >4ч ----

def test_tech_duty_within_norm():
    well = _make_well_data()
    rows = [{"name": "Тех.дежурство компл. партии в действ.фонде", "volume": 3.0}]
    assert well._check_tech_duty_hours(rows)["status"] == "ok"


def test_tech_duty_exceeds_norm():
    well = _make_well_data()
    rows = [{"name": "Тех.дежурство компл. партии в действ.фонде", "volume": 8.0}]
    assert well._check_tech_duty_hours(rows)["status"] == "bad"


# ---- Часы "Работа партии" vs продолжительность сессии ----
# Реальный акт 06513 (задача 61/61.1, ЛГПО): одна и та же сессия (151ч по
# датам начала/окончания) была выставлена один раз на 151ч (верно), другой
# раз на 127ч (заниженный биллинг, не пойман ни одной другой проверкой).

def test_hours_vs_duration_match():
    well = _make_well_data(start_date="05.05.2026 11:00", end_date="11.05.2026 18:00")  # 151ч
    rows = [{"name": "Работа партии по ликвидации гидрато-парафиновой пробки (ЛГПО)",
             "unit": "час", "volume": 151.0}]
    assert well._check_billed_hours_vs_duration(rows)["status"] == "ok"


def test_hours_vs_duration_mismatch():
    well = _make_well_data(start_date="05.05.2026 11:00", end_date="11.05.2026 18:00")  # 151ч
    rows = [{"name": "Работа партии по ликвидации гидрато-парафиновой пробки (ЛГПО)",
             "unit": "час", "volume": 127.0}]
    assert well._check_billed_hours_vs_duration(rows)["status"] == "bad"


def test_hours_vs_duration_neutral_without_party_rows():
    well = _make_well_data()
    rows = [{"name": "Запись муфтовых соед.локатором муфт (ЛМ)", "unit": "точ.", "volume": 5.0}]
    assert well._check_billed_hours_vs_duration(rows)["status"] == "neutral"


def test_hours_vs_duration_ignores_tech_duty_and_short_hour_measurements():
    """Реальный акт 13237 (задача 34(S)): почасовая строка "Регистрация КВД
    в таймерном режиме" — 3ч из 21ч полной сессии, это НЕ ошибка (одна из
    множества операций многопунктового акта, не биллинг всей сессии).
    "Тех.дежурство" — отдельная проверка с другим порогом/смыслом."""
    well = _make_well_data(start_date="25.08.2026 05:00", end_date="26.08.2026 02:00")  # 21ч
    rows = [
        {"name": "Регистрация КВД в таймерном режиме,заб.", "unit": "час", "volume": 3.0},
        {"name": "Тех.дежурство компл. партии в действ.фонде", "unit": "1 пар/час", "volume": 2.0},
    ]
    assert well._check_billed_hours_vs_duration(rows)["status"] == "neutral"


# ---- Пересечение термометрии 200/500 ----

def test_thermometry_overlap_detected():
    well = _make_well_data()
    rows = [
        {"name": "Термометрия высокочувствит.  М 1:200", "interval_from": 1800.0, "interval_to": 1900.0},
        {"name": "Термометрия в НКТ или межтрубье  М1:500", "interval_from": 50.0, "interval_to": 2200.0},
    ]
    assert well._check_thermometry_overlap(rows)["status"] == "bad"


def test_thermometry_no_overlap():
    well = _make_well_data()
    rows = [
        {"name": "Термометрия высокочувствит.  М 1:200", "interval_from": 2390.0, "interval_to": 2500.0},
        {"name": "Термометрия в НКТ или межтрубье  М1:500", "interval_from": 2600.0, "interval_to": 2700.0},
    ]
    assert well._check_thermometry_overlap(rows)["status"] == "ok"


# ---- Километраж: исключение "переезд на другой объект" ----

class _FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class _FakePdf:
    def __init__(self, pages_text):
        self.pages = [_FakePage(t) for t in pages_text]


def test_km_relocation_note_detected():
    pdf_with_note = _FakePdf(["стр1", "... Приезд на базу (переезд на другой объект) ..."])
    pdf_without_note = _FakePdf(["стр1", "... Приезд на базу ..."])
    assert km_parser._has_relocation_note(pdf_with_note) is True
    assert km_parser._has_relocation_note(pdf_without_note) is False
