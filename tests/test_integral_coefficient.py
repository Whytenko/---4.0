"""
Регрессионные тесты построчного интегрального коэффициента.

Все кейсы взяты либо из реальных примеров в "Инструкции по проверке
акт-нарядов 2026", либо из реальных production-актов, на которых сегодня
были найдены и исправлены баги:
  - угол наклона >45° ошибочно сбрасывал коэффициент на 1.0 (реальные акты
    с углом 48.08°/56.78°/90.91° показывали 1.32, а расчёт — 1.17);
  - работы спецкабелем/дефектоскопия не зависят от угла вообще, хотя по
    умолчанию классифицируются как "скважинные" (реальный акт 000079);
  - "Всп.работы" / "Всп. работы" / "Всп.раб." — три варианта написания
    одного и того же в реальных актах, все должны классифицироваться
    одинаково.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.extractors.main_parser import FinalUnifiedParser

_parser = FinalUnifiedParser()


def test_real_example_vatieganskoe_cold_steep():
    # Инструкция 2026, задача 87: темп=-25.12, угол=26.75 -> скв.=1.49, парт.=1.34
    rows = [
        {"name": "Влагометрия скважинная  М1:500", "integral_coeff": 1.49},
        {"name": "Термометрия в НКТ или межтрубье  М1:500", "integral_coeff": 1.49},
        {"name": "Услуги партии по обслуживанию действ.скв. с прим.луб. без бригады КРС", "integral_coeff": 1.34},
        {"name": "Всп.работы на скв.при бором.(манометрии)", "integral_coeff": 1.34},
        {"name": "Тех.дежурство компл. партии в действ.фонде", "integral_coeff": 1.34},
        {"name": "Переезд комп.партии в действ.фонде,1 гр.дорог", "integral_coeff": 1.34},
    ]
    status, details = _parser._check_integral_rows(rows, "-25,12", "26,75")
    assert status == "ok", details


def test_real_example_vatieganskoe_zero_temp_steep_angle():
    # Инструкция 2026, задача 53: темп=0, угол=36.15 -> скв.=1.15, парт.=1.00
    rows = [
        {"name": "Запись муфтовых соед.локатором муфт (ЛМ)", "integral_coeff": 1.15},
        {"name": "С/п скв.приб. ч/р лубрикатор", "integral_coeff": 1.15},
        {"name": "Услуги партии по обслуживанию действ.скв. с прим.луб.", "integral_coeff": 1.00},
        {"name": "Всп.работы на скв.при бором.(манометрии)", "integral_coeff": 1.00},
    ]
    status, details = _parser._check_integral_rows(rows, "0", "36,15")
    assert status == "ok", details


def test_wrong_value_is_caught():
    rows = [{"name": "Барометрия скв.  Запись точечная", "integral_coeff": 1.00}]
    status, details = _parser._check_integral_rows(rows, "-25,12", "26,75")
    assert status == "bad"
    assert any("❌" in line for line in details)


def test_no_valid_rows_is_neutral():
    status, details = _parser._check_integral_rows([{"name": "X", "integral_coeff": None}], "0", "10")
    assert status == "neutral"
    assert details == []


def test_angle_above_45_does_not_reset_to_baseline():
    """Реальный баг: 000080 (угол=56.78°, темп=-9°C) показывал акт=1.32,
    а старый код считал 1.17 (K_angle ошибочно сбрасывался на 1.0 при >45°)."""
    rows = [{"name": "Запись муфтовых соед.локатором муфт (ЛМ)", "integral_coeff": 1.32}]
    status, _ = _parser._check_integral_rows(rows, "-9", "56,78")
    assert status == "ok"

    # И ещё более крутой угол (000087: 90.91°) — тоже не должен сбрасываться.
    rows2 = [{"name": "С/п скв.приб. в откр.стволе или кол.", "integral_coeff": 1.32}]
    status2, _ = _parser._check_integral_rows(rows2, "-12,5", "90,91")
    assert status2 == "ok"


def test_spetskabel_defektoskopiya_ignores_angle():
    """Реальный акт 000079: угол=90.58°, темп=-9°C, но все строки
    (включая формально "скважинные" по названию) показывают акт=1.17 —
    для спецкабельных работ угол не действует вовсе."""
    rows = [
        {"name": "Запись дефектоскопии М1:200", "integral_coeff": 1.17},
        {"name": "Толщинометрия колонны приб.ЭМДС-С", "integral_coeff": 1.17},
        {"name": "С/п на спецкаб.в откpыт.ств.или колоне", "integral_coeff": 1.17},
        {"name": "Раб.спец.паpт.на спецкабеле", "integral_coeff": 1.17},
        {"name": "Всп. работы на скв.при дефектоскопии", "integral_coeff": 1.17},
        {"name": "Всп.pаботы на скв.при дефект.и толщин.колонны", "integral_coeff": 1.17},
    ]
    status, details = _parser._check_integral_rows(rows, "-9", "90,58")
    assert status == "ok", details


def test_vsp_raboty_spelling_variants_all_classified_as_party():
    for name in ("Всп.работы на скв.при бором.(манометрии)",
                  "Всп. работы на скв.при дефектоскопии",
                  "Всп.раб.на скв. приб. ГК d 36-42 мм."):
        assert _parser._classify_integral_work_type(name) == "party", name


def test_interval_columns_extracted_from_dynamic_header():
    table = [
        ["Наименование работ", "Номер расц.", "единица измерен", "интервал", "", "объем работ",
         "норма времени (мин.)", "расценка", "интег.коэфиц.", "затраты времени (мин.)", "стоимость работ, исслед. (руб.)"],
        ["", "", "", "от", "до", "", "", "", "", "", ""],
        ["Термометрия высокочувствит.  М 1:200", "273", "100 м", "2 390,0", "2 500,0",
         "1,10", "34,30", "653,89", "1,15", "45,28", "1 071,73"],
    ]
    rows = _parser._extract_rate_rows_from_table(table)
    assert len(rows) == 1
    assert rows[0]["interval_from"] == 2390.0
    assert rows[0]["interval_to"] == 2500.0


def test_perforation_surface_works_ignore_angle():
    """Реальные акты 12271, 13096, 13102 (темп=0, угол 30-70°): получение/
    снаряжение зарядов и работа перфораторной партии — работы на
    поверхности, идут с 1.00, а не со "скважинным" 1.15."""
    rows = [
        {"name": "Получение зарядов АДС, ПГД/БК, ПГРИ", "integral_coeff": 1.00},
        {"name": "Получение перфораторных зарядов", "integral_coeff": 1.00},
        {"name": "Снаряжение перфоратора ПНКТ", "integral_coeff": 1.00},
        {"name": "Работа перфораторной партии", "integral_coeff": 1.00},
        {"name": "Торпедирование, работа труборезом ТРК", "integral_coeff": 1.15},
    ]
    status, details = _parser._check_integral_rows(rows, "0", "69,57")
    assert status == "ok", details


def test_prayskurant_rate_expects_no_integral_coefficient():
    """Расценки Прейскуранта ("Лист1" в "17. Отчет по километражу.xlsx")
    договорные — коэффициенты ЕНВиР на них не действуют: ожидается 1.00
    при любой температуре/угле, а применённый коэффициент — расхождение."""
    row = {"name": "Переезд ЛПС", "rate_number": "1819"}
    status, details = _parser._check_integral_rows([dict(row, integral_coeff=1.00)], "-25,12", "90")
    assert status == "ok", details
    status, details = _parser._check_integral_rows([dict(row, integral_coeff=1.34)], "-25,12", "90")
    assert status == "bad", details
