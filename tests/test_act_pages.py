"""
Регрессионные тесты на два реальных сбоя пакетной проверки:
  - таблица расценок / итоги ("Всего к оплате") не уместились на титульном
    листе и ушли на следующий — стоимость и коэффициент по договору не
    находились, строки расценок терялись, лист-продолжение принимался за
    скан "АКТ-ЗАКАЗ";
  - один лист PDF с повреждённым шрифтом (акт 16003: лист "Оценка работы
    геофизической партии") ронял разбор всего акта — все поля "ошибка".
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.extractors.act_pages import act_text, continuation_page_indices
from src.extractors.main_parser import FinalUnifiedParser

_parser = FinalUnifiedParser()

_HEADER = [
    ["Наименование работ", "Номер расц.", "единица измерен", "интервал", "", "объем работ",
     "норма времени (мин.)", "расценка", "интег.коэфиц.", "затраты времени (мин.)", "стоимость работ, исслед. (руб.)"],
    ["", "", "", "от", "до", "", "", "", "", "", ""],
]
_ROW_THERMO = ["Термометрия высокочувствит.  М 1:200", "273", "100 м", "2 390,0", "2 500,0",
               "1,10", "34,30", "653,89", "1,15", "45,28", "1 071,73"]
_ROW_TRAVEL = ["Переезд комп.партии в действ.фонде,1 гр.дорог", "372", "км", "0,0", "0,0",
               "98,50", "1,60", "45,75", "1,00", "157,60", "4 506,38"]
_TOTALS = ["И т о г о по Акт-наpяду 2 037,74 48 015,62\nВсего к оплате 87 531,65"] + [None] * 10


class _FakePage:
    def __init__(self, text, tables=()):
        self._text = text
        self._tables = list(tables)

    def extract_text(self):
        return self._text

    def extract_tables(self):
        return self._tables


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages


def test_single_page_act_has_no_continuation():
    pdf = _FakePdf([
        _FakePage("Выполнение комплекса ГИРС по Договору №1\n...\nВсего к оплате 87 531,65"),
        _FakePage("АКТ - ЗАКАЗ на производство ГИРС"),
    ])
    assert continuation_page_indices(pdf, 0) == []
    assert act_text(pdf, 0) == pdf.pages[0].extract_text()


def test_totals_on_next_page_are_joined():
    pdf = _FakePdf([
        _FakePage("Выполнение комплекса ГИРС по Договору №1\nТермометрия ..."),
        _FakePage("Всего с учетом коэффициента 1,330 87 531,65\nВсего к оплате 87 531,65"),
        _FakePage("АКТ - ЗАКАЗ на производство ГИРС"),
    ])
    assert continuation_page_indices(pdf, 0) == [1]
    text = act_text(pdf, 0)
    assert _parser._parse_total_cost(text) == "87531.65"
    assert _parser._parse_contract_coefficient_from_act(text) == 1.33


def test_foreign_or_scanned_next_page_is_not_joined():
    # Следующий лист — другой документ или скан без текста: не приклеиваем.
    foreign = _FakePdf([_FakePage("Выполнение комплекса ГИРС по Договору №1"),
                        _FakePage("АКТ - ЗАКАЗ на производство ГИРС\nВсего к оплате 1,00")])
    scanned = _FakePdf([_FakePage("Выполнение комплекса ГИРС по Договору №1"), _FakePage("")])
    assert continuation_page_indices(foreign, 0) == []
    assert continuation_page_indices(scanned, 0) == []


def test_rate_rows_continue_on_next_page_without_header():
    pdf = _FakePdf([
        _FakePage("титул", [_HEADER + [_ROW_THERMO]]),
        _FakePage("продолжение", [[_ROW_TRAVEL, _TOTALS]]),
    ])
    rows = _parser._extract_rate_rows_page1(pdf, 0, [1])
    assert [r["rate_number"] for r in rows] == ["273", "372"]
    assert rows[1]["rate_price"] == 45.75
    assert rows[1]["volume"] == 98.5
    assert rows[1]["integral_coeff"] == 1.0
    # Без листа-продолжения (как было раньше) вторая строка терялась.
    assert len(_parser._extract_rate_rows_page1(pdf, 0)) == 1


def test_continuation_page_is_not_scan_candidate():
    pdf = _FakePdf([_FakePage("") for _ in range(5)])
    assert _parser._resolve_scan_candidates(pdf, 0, None, [1])[0] == 2
    assert _parser._resolve_scan_candidates(pdf, 0, None)[0] == 1


def test_broken_page_yields_empty_text_instead_of_crash():
    from pdfplumber.page import Page
    from pdfplumber.utils.exceptions import PdfminerException

    import src.utils.pdf_safe  # noqa: F401  (ставит защиту при импорте)

    class _BrokenPage(Page):
        def __init__(self):
            pass

        @property
        def layout(self):
            raise PdfminerException("'dict' object has no attribute 'decode'")

    assert _BrokenPage().parse_objects() == {}
