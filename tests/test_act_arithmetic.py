"""
Регрессионные тесты проверок, добавленных по итогам сплошного прохода по
139 реальным актам: арифметика строк и итогов титульного листа, сверка
реквизитов с акт-заказом, а также ложные срабатывания старых проверок
(барометрия при договорной расценке 1366, СПО из-за отброшенных долей
метра, летняя температура, СПО акт-заказа у задач по Прейскуранту).
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.extractors.main_parser import FinalUnifiedParser, WellData

_parser = FinalUnifiedParser()

_HEADER = [
    ["Наименование работ", "Номер расц.", "единица измерен", "интервал", "", "объем работ",
     "норма времени (мин.)", "расценка", "интег.коэфиц.", "затраты времени (мин.)", "стоимость работ, исслед. (руб.)"],
    ["", "", "", "от", "до", "", "", "", "", "", ""],
]


def _merged(text):
    return [text] + [None] * 10


def _well(**overrides):
    base = dict(
        filename="x.pdf", field="Повховское", order="1085468", depth="2959", angle="91,66",
        temperature="0", volume="", spo="", vm_task="", vm_price="", vm_count="",
        vm_total="", vm_table_count="", volume_sum_page1="", qty_sum_page3="",
        page2_start="", page2_end="", start_date="04.10.2026 18:30", end_date="05.10.2026 12:00",
    )
    base.update(overrides)
    return WellData(**base)


# Акт 05883: договорная расценка 1366 + переезды, коэффициент по договору
# начислен только на переезды.
_TABLE_05883 = _HEADER + [
    ["Определение положения забоя", "1366", "опер.", "399,0", "499,0", "1,00", "322,20", "55 089,36", "1,00", "322,20", "55 089,36"],
    ["Очистка внутренней полости НКТ", "1362", "опер.", "0,0", "0,0", "1,00", "", "90 607,50", "1,00", "", "90 607,50"],
    _merged("Стоимость договорных расценок 322,2 145 696,86"),
    ["Переезд комп.партии в действ.фонде,1 гр.дорог", "372", "км", "0,0", "0,0", "214,20", "1,60", "45,75", "1,00", "342,72", "9 799,65"],
    ["Переезд комп.партии в действ.фонде,бездорожье", "375", "км", "0,0", "0,0", "3,80", "3,50", "85,79", "1,00", "13,30", "326,00"],
    _merged("Стоимость проезда 356,02 10 125,65\nОбщий пробег кабеля"),
]
_TOTALS_05883 = (
    "И т о г о по Акт-наpяду 678,22 155 822,51\nИнтерпретация\nВсего с интерпретацией 155 822,51\n"
    "Всего по Акт-наряду 155 822,51\nВсего с учетом коэффициента 1,330 {total_k}\n"
    "Стоимость ВМ (тип ВМ) Кол-во Цена\nСтоимость расходных материалов (тип)\nВсего к оплате {to_pay}\n"
)


def test_row_cost_is_volume_times_price_times_coefficient():
    rows = _parser._extract_rate_rows_from_table(_TABLE_05883)
    assert _parser._check_row_costs(rows)["status"] == "ok"
    rows[2]["cost"] = 9999.0
    result = _parser._check_row_costs(rows)
    assert result["status"] == "bad"
    assert "№372" in result["details"][0]


def test_totals_contract_coefficient_not_applied_to_prayskurant():
    rows = _parser._extract_rate_rows_from_table(_TABLE_05883)
    good = _TOTALS_05883.format(total_k="159 163,97", to_pay="159 163,97")
    assert _parser._check_act_totals(rows, good)["status"] == "ok"
    # Коэффициент 1,33 начислен на весь акт, включая договорные расценки.
    wrong = _TOTALS_05883.format(total_k="207 243,94", to_pay="207 243,94")
    result = _parser._check_act_totals(rows, wrong)
    assert result["status"] == "bad"
    assert any("Прейскуранта" in line for line in result["details"])


def test_totals_to_pay_includes_vm():
    rows = _parser._extract_rate_rows_from_table(_TABLE_05883)
    text = _TOTALS_05883.format(total_k="159 163,97", to_pay="503 064,47").replace(
        "Стоимость ВМ (тип ВМ) Кол-во Цена", "Стоимость ВМ (тип ВМ) Кол-во Цена 343 900,50"
    )
    assert _parser._check_act_totals(rows, text)["status"] == "ok"
    assert _parser._check_act_totals(rows, text.replace("503 064,47", "159 163,97"))["status"] == "bad"


def test_unbilled_research_block_excluded_from_totals_and_integral():
    """Акты на спецкабеле (000079, 12303): скважинные исследования к
    оплате не предъявлены — в строке подытога одно число вместо двух."""
    table = _HEADER + [
        ["ГК приб.с сцинт.счетч. d >60 мм. М1:200", "076", "100 м", "800,0", "2 048,0", "12,98", "17,50", "418,45", "1,00", "", "5 431,48"],
        _merged("Стоимость скважинных исследований для расчета интерпретации без интегрального коэффициента: 5 431,48\n"
                "Стоимость скважинных исследований с интегральным коэффициентом: 404,1"),
        ["Раб.спец.паpт.на спецкабеле", "464", "1 пар/час", "0,0", "0,0", "28,00", "60,00", "10 156,06", "1,00", "1 680,00", "284 369,68"],
        _merged("Стоимость дополнительных работ 2 454,08 284 369,68"),
    ]
    rows = _parser._extract_rate_rows_from_table(table)
    assert rows[0]["billed"] is False and rows[1]["billed"] is True
    text = ("И т о г о по Акт-наpяду 5 040,64 284 369,68\nВсего по Акт-наряду 284 369,68\n"
            "Всего с учетом коэффициента 1,330 378 211,67\nСтоимость ВМ (тип ВМ) Кол-во Цена\nВсего к оплате 378 211,67\n")
    assert _parser._check_act_totals(rows, text)["status"] == "ok"
    # Угол 93,9° дал бы 1,15 для ГК — но строка не оплачивается, не сверяем.
    status, details = _parser._check_integral_rows(rows, "0", "93,93")
    assert status == "ok", details


def test_requisites_zakaz_match_and_mismatch():
    well = _well()
    well.well_number, well.bush, well.performed_tasks = "1052Г", "29", "35(S)"
    well.page2_requisites = {"order": "1085468", "well": "1052Г", "bush": "29", "depth": "2959,1",
                             "angle": "91,66", "task": "35(S)"}
    assert well._check_requisites_zakaz()["status"] == "ok"
    well.page2_requisites["angle"] = "19,66"
    result = well._check_requisites_zakaz()
    assert result["status"] == "bad"
    assert "Угол наклона" in result["details"][0]
    well.page2_requisites = {}
    assert well._check_requisites_zakaz()["status"] == "neutral"


def test_requisites_zakaz_tech_duty_and_warnings():
    well = _well()
    well.page2_requisites = {"order": "1085468", "tech_duty_minutes": "240", "spo_condition": "4",
                             "idle_reasons": "ожидание подъёмника"}
    well.tech_duty_hours_title = 4.0
    well.spo_condition_code = "3"
    result = well._check_requisites_zakaz()
    assert result["status"] == "ok"
    assert any("Условия СПО" in line for line in result["details"])
    assert any("ожидание подъёмника" in line for line in result["details"])
    well.tech_duty_hours_title = 6.0
    assert well._check_requisites_zakaz()["status"] == "bad"


def test_barometry_task53_looked_up_in_appendix():
    well = _well()
    well.task_number = "53"
    lump = [{"name": "Определение положения забоя", "rate_number": "1366"}]
    # Задача оплачена расценкой 1366 — барометрия должна быть в Приложении №1.
    assert well._check_barometry_task53(lump, True)["status"] == "ok"
    # Нет нигде — предупреждение, на итог по акту не влияет.
    missing = well._check_barometry_task53(lump, False)
    assert missing["status"] == "conditional_ok"
    assert any("⚠" in line for line in missing["details"])
    # Приложение — скан: проверить нечем, это не расхождение.
    assert well._check_barometry_task53(lump, None)["status"] == "neutral"
    # Барометрия строкой в самом акт-наряде — Приложение не нужно.
    rows = [{"name": "Барометрия скв. Запись точечная", "rate_number": "301"}]
    assert well._check_barometry_task53(rows, False)["status"] == "ok"
    assert well._check_barometry_task53(
        [{"name": "Запись муфтовых соед.", "rate_number": "217"}]
    )["status"] == "conditional_ok"


def test_vm_price_accepts_both_max_and_min_density():
    well = _well(vm_task="58.134", vm_price="2578,99", vm_count="30", vm_total="77369,70")
    well._get_vm_prices = lambda task, unit_price=None: (2578.99, 1799.00)
    assert well._check_vm_cost()["status"] == "ok"      # цена при max плотности
    well.vm_price, well.vm_total = "1799,00", "53970,00"
    assert well._check_vm_cost()["status"] == "ok"      # цена при min плотности
    well.vm_price, well.vm_total = "2000,00", "60000,00"
    assert well._check_vm_cost()["status"] == "bad"     # ни та, ни другая


def test_spo_fraction_of_metre_is_not_mismatch():
    # Акт 000081: 60,63 (=6063 м) на титуле, 6063,53 в справке.
    well = _well(volume="60,63", spo="6063.53")
    assert well._check_volume_spo()["status"] == "ok"
    # Акт 000080: в справке прибор + шаблон (32,22 + 62,00).
    well = _well(volume="32,22", spo="9422.05")
    assert well._check_volume_spo()["status"] == "bad"
    well.spo_row_candidates = [94.22]
    assert well._check_volume_spo()["status"] == "ok"


def test_spo_zakaz_neutral_for_lump_sum_task():
    well = _well()
    well.page2_spo = "8.41"
    rows = [{"name": "Определение профиля приемистости", "rate_number": "1364", "volume": 1.0}]
    assert well._check_spo_zakaz(rows)["status"] == "neutral"
    rows = [{"name": "Запись ЛМ", "rate_number": "217", "volume": 1.0}]
    assert well._check_spo_zakaz(rows)["status"] == "bad"


def test_volume_scope_includes_contract_block_and_diff_by_rate():
    # Акт 12303: скважинные исследования + договорные расценки.
    rows = [
        {"name": "ГК", "rate_number": "76", "volume": 12.98, "block": "research"},
        {"name": "Профилемер", "rate_number": "1307", "volume": 1.0, "block": "contract"},
        {"name": "Услуги партий", "rate_number": "5", "volume": 1.0, "block": "extra"},
        {"name": "Переезд", "rate_number": "372", "volume": 100.8, "block": "travel"},
    ]
    assert abs(_parser._appendix_scope_volume(rows) - 13.98) < 0.001
    assert _parser._volume_diff_by_rate(rows, {"76": 12.98, "1307": 1.0}) == []
    lines = _parser._volume_diff_by_rate(rows, {"76": 10.0, "1307": 1.0})
    assert len(lines) == 1 and "12.98" in lines[0] and "10.00" in lines[0]


def test_summer_temperature_zero_on_title_is_ok():
    from datetime import datetime

    from src.extractors import table_parser

    original = table_parser.get_table_data
    start, end = datetime(2026, 8, 10, 8), datetime(2026, 8, 10, 12)
    try:
        table_parser.get_table_data = lambda dt, well_type: 17.0
        assert table_parser._compute_temp_stats("ВАТЬЕГАН", start, end, 0.0)["status"] == "ok"
        table_parser.get_table_data = lambda dt, well_type: -12.0
        assert table_parser._compute_temp_stats("ВАТЬЕГАН", start, end, 0.0)["status"] == "bad"
    finally:
        table_parser.get_table_data = original
