"""
Отчёт: задача с листа 1, задача по заявке и причина смены задачи; для ПВР —
перфоратор, тип и количество зарядов. Примеры — реальные акты 12472
(заявка 35, недоход 500.4), 12272 (заявка 80(S), выполнена 80(P)), 13096
(581.416, ВМ на титуле), 12373 (582, ВМ не выставлено).
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
        filename="x.pdf", field="Повховское", order="1", depth="2500", angle="20",
        temperature="0", volume="", spo="", vm_task="", vm_price="", vm_count="",
        vm_total="", vm_table_count="", volume_sum_page1="", qty_sum_page3="",
        page2_start="", page2_end="", start_date="14.08.2026 08:00", end_date="14.08.2026 20:00",
    )
    base.update(overrides)
    return WellData(**base)


_ACT_12472 = (
    "о том, что «14» августа 2026 года на скважине № 3391 куст № 209 м/р (площадь) Повховского "
    "при проведении задачи №35(5): 1. В 11.00 получили стоянку прибора СОВА-9 (диаметр 38 мм) на глубине 335 м."
)


def test_task_change_with_reason_from_contractor_act():
    well = _well()
    well.performed_tasks, well.embedded_zayavka_task = "500.4", "35"
    well.contractor_acts = [(3, "о том, что нами проверена готовность скважины"), (8, _ACT_12472)]
    note = well.task_change_note()
    assert note.startswith("Заявка: задача 35 → выполнена 500.4")
    assert "стоянку прибора СОВА-9" in note and "стр. 9" in note
    assert "3391" not in note  # шапка акта (дата, скважина, куст) отрезана


def test_refinement_is_not_task_change():
    well = _well()
    for performed, ordered in (("58.134", "58"), ("35(S)", "35"), ("53", "53")):
        well.performed_tasks, well.embedded_zayavka_task = performed, ordered
        assert well.task_change_note() == "", (performed, ordered)


def test_other_suffix_is_task_change_without_reason():
    well = _well()
    well.performed_tasks, well.embedded_zayavka_task = "80(P)", "80(S)"
    note = well.task_change_note()
    assert note.startswith("Заявка: задача 80(S) → выполнена 80(P)")
    assert "уточнить у подрядчика" in note


def test_nedokhod_without_recognised_zayavka():
    well = _well()
    well.performed_tasks = "500.4"
    well.contractor_acts = [(6, "о том, что «14» августа 2026 года на скважине № 1052г куст № 29 им В.И. Некрасова "
                                "месторождения, задача 58 не выполнена: стоянка шаблона 44 мм на глубине 1027 м")]
    note = well.task_change_note()
    assert note.startswith("Выполнена 500.4 (недоход)")
    assert note.split("Причина: ")[1].startswith("задача 58 не выполнена")


def test_pvr_from_vm_lines():
    text = (
        "Всего с учетом коэффициента 1,330 53 311,25\n"
        "Стоимость ВМ (тип ВМ) Кол-во Цена 1 283 412,79\n"
        "581.416 - ПКО102-АТ - ЗПК102-АТ-М-04 + ЗПК102-АТ-М-10 472 х 2 474,76 1 168 086,72\n"
        "581.416.1 - ПКО102-АТ - комплектующий набор 1 х 115 326,07 115 326,07\n"
        "Стоимость расходных материалов (тип)\nВсего к оплате 1 336 724,04\n"
    )
    summary = _parser._pvr_summary(text, [], "581.416", [])
    assert summary == "ПВР: перфоратор ПКО102-АТ, заряд ЗПК102-АТ-М-04 + ЗПК102-АТ-М-10 — 472 шт."


def test_pvr_two_vm_lines_same_charge_are_summed():
    text = (
        "Стоимость ВМ (тип ВМ) Кол-во Цена 488 749,50\n"
        "58.134 - ПК89КЛ ORION (К) - ORION 89-02 (SDP) 200 х 1 799,00 359 800,00\n"
        "58.134 - ПК89КЛ ORION (К) - ORION 89-02 (SDP) 50 х 2 578,99 128 949,50\n"
        "Стоимость расходных материалов (тип)\n"
    )
    assert _parser._pvr_summary(text, [], "58.134", []).endswith("— 250 шт.")


def test_pvr_without_vm_takes_perforator_from_act():
    acts = [(11, "о том, что перфоратор (тип)_Скорпион 73 Сработал/не сработал нужное подчеркнуть")]
    summary = _parser._pvr_summary("Стоимость ВМ (тип ВМ) Кол-во Цена\nВсего к оплате 1,00", [], "582", acts)
    assert summary.startswith("ПВР: перфоратор Скорпион 73")
    assert "не указано" in summary
    # Не ПВР и без ВМ — ничего.
    assert _parser._pvr_summary("", [], "35(S)", acts) == ""


def test_blank_template_is_not_anomaly():
    text = ("Мы, нижеподписавшиеся составили настоящий акт о том, что перфоратор (тип) ПКО-102 АТ "
            "Сработал/не сработал нужное подчеркнуть Убедившись по характерному звуку на устье")
    assert _parser._extract_contractor_comment(text) == ""


def test_pvr_summary_added_to_comment_when_no_itp_spec():
    well = _well()
    well.pvr_summary = "ПВР: перфоратор Скорпион 73, кол-во зарядов в акт-наряде не указано (ВМ не выставлено)"
    well._finalize_contractor_comment([{"name": "Тех.дежурство перфораторной партии", "volume": 5.5}])
    assert well.contractor_comment == "Тех.деж. 5.5ч. " + well.pvr_summary


def test_reason_header_with_comma_before_area():
    # Акт 13083: "м/р, (площадь) Ватьеганское При выполнении задачи..."
    well = _well()
    well.performed_tasks, well.embedded_zayavka_task = "53", "58"
    well.contractor_acts = [(7, "о том, что «25» 08 2026 года на скважине № 2228 куст №186 м/р, (площадь) "
                                "Ватьеганское При выполнении задачи №58 получили недоход")]
    assert well.task_change_note().split("Причина: ")[1].startswith("При выполнении задачи №58")
