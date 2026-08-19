"""
Регрессионные тесты классификации документов пакета и сверки акта с заявкой.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.extractors import doc_linking
from src.extractors.main_parser import WellData


def _make_well_data(**overrides):
    base = dict(
        filename="x.pdf", field="Ватьеганское", order="1", depth="2500", angle="36,5",
        temperature="0", volume="", spo="", vm_task="", vm_price="", vm_count="",
        vm_total="", vm_table_count="", volume_sum_page1="", qty_sum_page3="",
        page2_start="", page2_end="", start_date="01.12.2025 08:00", end_date="02.12.2025 08:00",
    )
    base.update(overrides)
    return WellData(**base)


def test_akt_naryad_not_misclassified_as_prostoy():
    """Реальный баг: акт №00081 содержит 'в межтрубном ПРОСТранстве' —
    ложно матчился на обрывок слова 'прост'. Классификатор теперь требует
    целую фразу 'акт на простой'."""
    text = (
        "АКТ - HАРЯД № 00081 от 06.01.2026\n"
        "Задача №301 Определение сборкой приборов тех.состояния НКТ и границ "
        "разделов смеси в межтрубном пространстве в свкажинах при работающем ЭЦН\n"
    )
    assert doc_linking.classify_text(text) == "akt_naryad"


def test_real_akt_prostoy_still_matches():
    text = (
        "АКТ\n"
        "на простой геофизической партии №_3-08_ ОАО Когалымнефтегеофизика\n"
        "Скважина №_1115_ кустовая площадка №_43Б_ Повховского месторождения\n"
    )
    assert doc_linking.classify_text(text) == "akt_prostoy"


def test_zayavka_classified_correctly():
    text = "ЗАЯВКА\nна проведение промыслово-геофизических исследований скважин\n"
    assert doc_linking.classify_text(text) == "zayavka"


def test_zayavka_field_parsing_case_insensitive():
    text = "на скважину № 1867 куста № 4 месторождение Ватьеганское\n"
    parsed = doc_linking.parse_zayavka_text(text)
    assert parsed["field"] == "Ватьеганское"
    assert parsed["bush"] == "4"
    assert parsed["well"] == "1867"


def test_match_by_order_number_when_available():
    zayavka = {"order": "1023237", "field": "Ватьеганское", "bush": "4", "well": "1867", "task": ""}
    well = _make_well_data(order="1023237", field="Ватьеганское")
    well.bush = "999"  # заведомо другой куст — но матч всё равно должен пройти по заказу
    well.well_number = "1"
    match = doc_linking.match_zayavka_for_well(well, [zayavka])
    assert match is zayavka


def test_match_falls_back_to_bush_and_well_when_no_order_text():
    zayavka = {"order": "", "field": "Ватьеганское", "bush": "52", "well": "4836", "task": "58"}
    well = _make_well_data(order="не найдено", field="Ватьеганское")
    well.bush = "52"
    well.well_number = "4836"
    match = doc_linking.match_zayavka_for_well(well, [zayavka])
    assert match is zayavka


def test_task_mismatch_is_flagged():
    zayavka = {"order": "", "field": "Ватьеганское", "bush": "52", "well": "4836", "task": "58"}
    well = _make_well_data()
    well.task_number = "58.141"
    result = doc_linking.check_against_zayavka(well, zayavka)
    assert result["status"] == "bad"


def test_nedokhod_500_4_is_expected_not_flagged():
    zayavka = {"order": "", "field": "Ватьеганское", "bush": "52", "well": "4836", "task": "58"}
    well = _make_well_data()
    well.task_number = "500.4"
    result = doc_linking.check_against_zayavka(well, zayavka)
    assert result["status"] == "ok"
    assert any("Недоход" in line for line in result["details"])
