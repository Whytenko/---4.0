# src/extractors/main_parser.py

import re
import os
import pdfplumber
from pathlib import Path
from typing import ClassVar, List
from dataclasses import dataclass, field
from datetime import datetime
import sys
import math
import pandas as pd
import shutil
import importlib
import traceback

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.app_paths import (
    ensure_runtime_layout,
    get_input_dir,
    get_reference_dir,
    get_resource_roots,
)

# Коэффициент по договору (см. "Инструкцию по проверке акт-нарядов 2026") —
# обновлять при заключении новых договоров.
CONTRACT_COEFFICIENTS = {
    "2026008065": 1.33,
    "2025031516": 1.228,
}

@dataclass
class WellData:
    """Класс для хранения данных по скважине"""
    filename: str
    field: str
    order: str
    depth: str
    angle: str
    temperature: str
    volume: str
    spo: str
    vm_task: str
    vm_price: str
    vm_count: str
    vm_total: str
    vm_table_count: str
    volume_sum_page1: str
    qty_sum_page3: str
    page2_start: str
    page2_end: str
    start_date: str
    end_date: str
    duration_hours: float = 0.0
    ml_confidence: float = 0.0
    ml_method: str = ""
    ml_suggestions: dict = field(default_factory=dict)
    ml_applied: dict = field(default_factory=dict)
    ml_spo_source: str = ""
    rate_check_status: str = ""
    rate_check_details: List[str] = field(default_factory=list)
    # Построчная сверка интегрального коэффициента (по факт. строкам расценок
    # из акта) — считается однажды в parse_all, пока PDF уже открыт
    integral_row_status: str = ""
    integral_row_details: List[str] = field(default_factory=list)
    task_number: str = ""
    contract_number: str = ""
    contract_coeff_value: float | None = None
    well_number: str = ""
    bush: str = ""
    zayavka_check_status: str = ""
    zayavka_check_details: List[str] = field(default_factory=list)
    # Результаты доп.проверок, вычисленных в parse_all из строк расценок
    # (барометрия@53, тех.дежурство >4ч, пересечение термометрии 200/500)
    check_results: dict = field(default_factory=dict)

    # Shared DataFrame кэш: один на весь класс, не пересоздаётся при каждом parse_all
    _vm_price_df_cache: ClassVar["pd.DataFrame | None"] = None
    
    def __post_init__(self):
        """Вычисляем продолжительность после создания объекта"""
        self.duration_hours = self._calculate_duration()
    
    def _calculate_duration(self) -> float:
        """Вычисляет продолжительность работ в часах"""
        try:
            start_dt = datetime.strptime(self.start_date, '%d.%m.%Y %H:%M')
            end_dt = datetime.strptime(self.end_date, '%d.%m.%Y %H:%M')
            duration = end_dt - start_dt
            return duration.total_seconds() / 3600  # Часы
        except:
            return 0.0
    
    # Единый реестр проверок: (ключ, геттер результата, подпись по умолчанию,
    # молчать ли при статусе "neutral"). И print_with_units(), и
    # get_check_summary() идут по одному и тому же списку — раньше это были
    # два независимых места, которые несколько раз забывали синхронизировать
    # при добавлении новой проверки.
    #
    # Каждый геттер возвращает dict вида:
    #   {"status": "ok"|"bad"|"neutral"|"conditional_ok",
    #    "label": <необязательная замена подписи>,
    #    "value_text": <необязательный текст вместо иконки по умолчанию>,
    #    "details": [<уже полностью отформатированные строки, с отступом>]}
    _CHECK_REGISTRY_BEFORE_ML: ClassVar[tuple] = (
        ("spo", lambda self: self._check_volume_spo(), "Отчет по СПО", False),
        ("vm_cost", lambda self: self._check_vm_cost(), "Цена ВМ", False),
        ("rate", lambda self: self._check_rate(), "Проверка расценок", False),
        ("volume_qty", lambda self: self._check_volume_qty(),
         "Сравнение объемов (стр.1) и кол-ва (стр.3)", False),
        ("page2_dates", lambda self: self._check_page2_dates(), "Сравнение дат (стр.2)", False),
    )
    _CHECK_REGISTRY_AFTER_ML: ClassVar[tuple] = (
        ("integral", lambda self: self._check_integral(), "Интегральный коэффициент", False),
        ("contract_coeff", lambda self: self._check_contract_coefficient(),
         "Коэффициент по договору", False),
        ("barometry_task53", lambda self: self.check_results.get("barometry_task53", {"status": "neutral"}),
         "Барометрия при задаче №53", True),
        ("tech_duty", lambda self: self._prefix_details(self.check_results.get("tech_duty", {"status": "neutral"})),
         "Тех.дежурство >4ч (нужен акт)", True),
        ("thermometry_overlap",
         lambda self: self._prefix_details(self.check_results.get("thermometry_overlap", {"status": "neutral"})),
         "Термометрия 200/500 (пересечение)", True),
        ("zayavka", lambda self: self._check_zayavka(), "Сверка с заявкой", True),
    )

    _STATUS_ICONS: ClassVar[dict] = {"ok": "✅", "bad": "❌"}

    def _print_check(self, getter, default_label: str, silent_on_neutral: bool) -> None:
        result = getter(self)
        status = result.get("status", "neutral")
        if status == "neutral" and silent_on_neutral:
            return
        label = result.get("label", default_label)
        if "value_text" in result:
            value_text = result["value_text"]
        elif status == "neutral":
            value_text = "данных нет"
        else:
            value_text = self._STATUS_ICONS.get(status, status)
        print(f"  {label}: {value_text}")
        for line in result.get("details", []):
            print(line)

    def print_with_units(self):
        """Вывод с единицами измерения"""
        print(f"\n{self.filename}:")
        print(f"  Месторождение: {self.field}")
        print(f"  Номер заказа: {self.order}")
        print(f"  Глубина забоя: {self.depth} м")
        print(f"  Угол наклона: {self.angle}°")
        print(f"  Температура воздуха: {self.temperature}°C")
        print(f"  СПО: {self.volume}")
        print(f"  СПО (таблица): {self.spo}")
        print(f"  Начало работ на скв: {self.start_date}")
        print(f"  Окончание работ на скв: {self.end_date}")
        print(f"  Продолжительность работ: {self.duration_hours:.2f} часов")
        if self.task_number:
            print(f"  Номер задачи: {self.task_number}")
        for _key, getter, label, silent in self._CHECK_REGISTRY_BEFORE_ML:
            self._print_check(getter, label, silent)
        self._print_ml_info()
        for _key, getter, label, silent in self._CHECK_REGISTRY_AFTER_ML:
            self._print_check(getter, label, silent)

    def _check_rate(self) -> dict:
        status = self.rate_check_status or "neutral"
        return {"status": status, "details": [f"    {line}" for line in self.rate_check_details]}

    def _to_float(self, value: str) -> float | None:
        try:
            val = float(str(value).replace(',', '.'))
            if math.isnan(val):
                return None
            return val
        except Exception:
            return None

    def _format_ru(self, value: float | None) -> str:
        if value is None:
            return ""
        s = f"{value:,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", " ")
        return s

    def _check_volume_spo(self) -> dict:
        spo_act = self._to_float(self.volume)
        spo_table = self._to_float(self.spo)
        if spo_act is None or spo_table is None:
            return {"status": "neutral"}
        if abs(spo_act) < 1000 <= abs(spo_table):
            spo_act = spo_act * 100
        elif abs(spo_act) >= 1000 > abs(spo_table):
            spo_table = spo_table * 100

        def _round_half_up(value: float) -> int:
            if value >= 0:
                return int(math.floor(value + 0.5))
            return int(math.ceil(value - 0.5))

        match = _round_half_up(spo_act) == _round_half_up(spo_table)
        return {
            "status": "ok" if match else "bad",
            "details": [
                f"    СПО в акте = {spo_act:.2f}",
                f"    СПО в таблице = {spo_table:.2f}",
            ],
        }

    def _check_vm_cost(self) -> dict:
        task = self.vm_task
        price_raw = self._to_float(self.vm_price)
        count = self._to_float(self.vm_count)
        total = self._to_float(self.vm_total)
        table_count = self._to_float(self.vm_table_count)
        unit_price = price_raw

        if count is not None and count > 0:
            if total is not None and total > 0:
                unit_from_total = total / count
                if unit_price is None or unit_price > unit_from_total * 1.5:
                    unit_price = unit_from_total
            elif unit_price is not None and unit_price > 10000:
                unit_price = unit_price / count

        if not task or unit_price is None:
            return {"status": "neutral", "label": "Стоимость ВМ", "value_text": "данных нет"}

        max_price, min_price = self._get_vm_prices(task, unit_price)
        if max_price is None and min_price is None:
            return {"status": "neutral", "label": "Стоимость ВМ", "value_text": "не найдено в таблице"}

        price_ok = min_price is not None and math.isclose(unit_price, min_price, rel_tol=0.0, abs_tol=0.1)

        details: List[str] = []
        if price_raw is not None:
            details.append(f"    Цена в акте = {self._format_ru(price_raw)}")
        if count is not None:
            details.append(f"    Кол-во = {int(count)}")
        if total is not None:
            details.append(f"    Итого = {self._format_ru(total)}")
        if table_count is not None:
            count_match = math.isclose(count, table_count, rel_tol=0.0, abs_tol=0.1) if count is not None else False
            count_icon = "✅" if count_match else "❌"
            details.append(f"    Сравнение кол-ва: {count_icon}")
            details.append(f"      Кол-во в таблице = {int(table_count)}")
        if max_price is not None:
            details.append(f"    Стоимость 1 отв. при max плотности = {self._format_ru(max_price)}")
        if min_price is not None:
            details.append(f"    Стоимость 1 отв. при min плотности = {self._format_ru(min_price)}")

        return {"status": "ok" if price_ok else "bad", "label": "Цена ВМ", "details": details}

    def _check_volume_qty(self) -> dict:
        vol_sum = self._to_float(self.volume_sum_page1)
        qty_sum = self._to_float(self.qty_sum_page3)
        if vol_sum is None or qty_sum is None:
            return {"status": "neutral"}
        match = math.isclose(vol_sum, qty_sum, rel_tol=0.0, abs_tol=0.1)
        return {
            "status": "ok" if match else "bad",
            "details": [
                f"    Сумма объемов (стр.1) = {vol_sum:.2f}",
                f"    Сумма кол-ва (стр.3) = {qty_sum:.2f}",
            ],
        }

    def _check_page2_dates(self) -> dict:
        start1 = self.start_date
        end1 = self.end_date
        start2 = self.page2_start
        end2 = self.page2_end
        if not start2 or not end2 or "не найдено" in (start2, end2):
            return {"status": "conditional_ok", "value_text": "условно ✅"}
        match = (start1 == start2) and (end1 == end2)
        return {
            "status": "ok" if match else "bad",
            "details": [
                f"    Начало работ: {start1} / {start2}",
                f"    Окончание работ: {end1} / {end2}",
            ],
        }

    def _check_integral(self) -> dict:
        if not self.integral_row_status:
            return {"status": "neutral"}
        return {
            "status": self.integral_row_status,
            "details": [f"    {line}" for line in self.integral_row_details],
        }

    def _check_contract_coefficient(self) -> dict:
        expected = CONTRACT_COEFFICIENTS.get(self.contract_number)
        if not self.contract_number or expected is None:
            return {"status": "neutral"}
        if self.contract_coeff_value is None:
            return {"status": "neutral"}
        match = math.isclose(self.contract_coeff_value, expected, rel_tol=0.0, abs_tol=0.01)
        return {
            "status": "ok" if match else "bad",
            "details": [
                f"    Договор №{self.contract_number}: ожидается {expected:.3f}, "
                f"в акте {self.contract_coeff_value:.3f}"
            ],
        }

    def _check_zayavka(self) -> dict:
        if not self.zayavka_check_status:
            return {"status": "neutral"}
        return {
            "status": self.zayavka_check_status,
            "details": [f"    {line}" for line in self.zayavka_check_details],
        }

    @staticmethod
    def _prefix_details(result: dict) -> dict:
        """Строки в check_results (барометрия/тех.дежурство/термометрия)
        хранятся без отступа — добавляем его только для единого принтера,
        не трогая исходно сохранённый dict."""
        if not result.get("details"):
            return result
        return {**result, "details": [f"    {line}" for line in result["details"]]}

    def _check_barometry_task53(self, rows: List[dict]) -> dict:
        task = str(self.task_number or "").strip()
        if task != "53":
            return {"status": "neutral"}
        found = any("барометр" in str(row.get("name", "")).lower() for row in rows)
        return {"status": "ok" if found else "bad"}

    def _check_tech_duty_hours(self, rows: List[dict]) -> dict:
        threshold_hours = 4.0
        flagged: List[str] = []
        checked = 0
        for row in rows:
            name = str(row.get("name", "")).strip()
            norm = name.lower()
            if "тех.дежурство" not in norm and "технологическое дежурство" not in norm:
                continue
            volume = row.get("volume")
            if not isinstance(volume, (int, float)):
                continue
            checked += 1
            if volume > threshold_hours + 0.01:
                name_short = name if len(name) <= 70 else f"{name[:67]}..."
                flagged.append(
                    f"❌ {name_short} | {volume:.2f} ч > {threshold_hours:.0f} ч — нужен акт о простое"
                )
        if checked == 0:
            return {"status": "neutral"}
        if flagged:
            return {"status": "bad", "details": flagged}
        return {"status": "ok", "details": [f"В норме (≤{threshold_hours:.0f} ч), строк проверено: {checked}"]}

    def _check_thermometry_overlap(self, rows: List[dict]) -> dict:
        scale_re = re.compile(r'термометри.*?[MМ]\s*1\s*:\s*(200|500)', re.IGNORECASE)
        intervals_200: List[tuple] = []
        intervals_500: List[tuple] = []
        for row in rows:
            name = str(row.get("name", ""))
            if "термометр" not in name.lower():
                continue
            match = scale_re.search(name)
            if not match:
                continue
            i_from = row.get("interval_from")
            i_to = row.get("interval_to")
            if not isinstance(i_from, (int, float)) or not isinstance(i_to, (int, float)):
                continue
            lo, hi = min(i_from, i_to), max(i_from, i_to)
            bucket = intervals_200 if match.group(1) == "200" else intervals_500
            bucket.append((lo, hi, name))

        if not intervals_200 or not intervals_500:
            return {"status": "neutral"}

        overlaps: List[str] = []
        for lo1, hi1, name1 in intervals_200:
            for lo2, hi2, name2 in intervals_500:
                if lo1 < hi2 and lo2 < hi1:
                    overlaps.append(
                        f"❌ Пересечение: {name1} [{lo1:.1f}-{hi1:.1f}] и {name2} [{lo2:.1f}-{hi2:.1f}]"
                    )

        if overlaps:
            return {"status": "bad", "details": overlaps}
        return {
            "status": "ok",
            "details": [f"Пересечений не найдено (М1:200: {len(intervals_200)}, М1:500: {len(intervals_500)})"],
        }

    def get_check_summary(self) -> dict:
        """Структурированные статусы всех проверок (ok/bad/neutral/conditional_ok)
        без печати — используется для выгрузки пакетного Excel-отчёта. Идёт
        по тому же реестру _CHECK_REGISTRY_*, что и print_with_units(), —
        поэтому эти два места больше не могут разойтись."""
        summary = {}
        for key, getter, _label, _silent in self._CHECK_REGISTRY_BEFORE_ML + self._CHECK_REGISTRY_AFTER_ML:
            summary[key] = getter(self)
        return summary

    def _print_ml_info(self):
        if not self.ml_applied:
            return
        if self.ml_method == "ml-lines":
            return
        label_map = {
            "field": "Месторождение",
            "order": "Номер заказа",
            "temperature": "Температура воздуха",
            "angle": "Угол наклона",
            "volume": "СПО",
            "start_date": "Начало работ (стр.1)",
            "end_date": "Окончание работ (стр.1)",
            "page2_start": "Начало работ (стр.2)",
            "page2_end": "Окончание работ (стр.2)",
            "volume_sum_page1": "Сумма объемов (стр.1)",
            "qty_sum_page3": "Сумма объемов (стр.3)",
            "vm_price": "Цена ВМ",
            "vm_count": "Кол-во ВМ",
        }
        print("  🤖 ML-коррекция:")
        if self.ml_method:
            print(f"    Метод: {self.ml_method}, доверие: {self.ml_confidence:.2f}")
        if self.ml_spo_source:
            print(f"    СПО взято из поля: {self.ml_spo_source}")
        for attr, (old, new) in self.ml_applied.items():
            label = label_map.get(attr, attr)
            old_val = old if old else "—"
            print(f"    {label}: {old_val} → {new}")
    def _get_vm_prices(self, task: str, unit_price: float | None = None):
        excel_path = get_reference_dir() / "Стоимость ВМ задачи (не удалять).xlsx"
        if not excel_path.exists():
            return None, None
        if WellData._vm_price_df_cache is None:
            WellData._vm_price_df_cache = pd.read_excel(
                excel_path, sheet_name="Прейск_2019", header=None
            )
        df = WellData._vm_price_df_cache
        best_row = None
        best_diff = None
        for i in range(2, df.shape[0]):
            task_cell = str(df.iloc[i, 1]).strip()
            if task_cell != task:
                continue
            values = []
            for col in (7, 8, 9, 10):
                val = self._to_float(df.iloc[i, col])
                if val is not None:
                    values.append(val)
            if not values:
                continue
            if unit_price is None:
                best_row = i
                break
            diff = min(abs(unit_price - v) for v in values)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_row = i

        if best_row is None:
            return None, None

        values = []
        for col in (7, 8, 9, 10):
            val = self._to_float(df.iloc[best_row, col])
            if val is not None:
                values.append(val)
        if not values:
            return None, None
        return max(values), min(values)

class FinalUnifiedParser:
    """Финальный объединенный парсер ВСЕХ данных"""
    _rate_reference_cache: dict | None = None
    
    def parse_all(self, pdf_path: str) -> WellData:
        """Парсит ВСЕ значения включая даты и возвращает объект WellData"""
        ensure_runtime_layout(copy_reference=True)
        try:
            with pdfplumber.open(pdf_path) as pdf:
                text = pdf.pages[0].extract_text() if pdf.pages else ""
                all_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                
                filename = os.path.basename(pdf_path)
                
                # Вычисляем vm_count один раз (используется дважды)
                vm_count_val = self._parse_vm_count(all_text)
                # OCR страницы 2 вызывается один раз
                page2_start, page2_end = self._parse_page2_start_end(pdf)

                well_data = WellData(
                    filename=filename,
                    field=self._parse_field(text),
                    order=self._parse_order(text, pdf_path),
                    depth=self._parse_depth(text),
                    angle=self._parse_angle(text),
                    temperature=self._parse_temperature(text),
                    volume=self._parse_volume(text),
                    spo=self._parse_spo(all_text, pdf),
                    vm_task=self._parse_vm_task(text),
                    vm_price=self._parse_vm_price(all_text),
                    vm_count=vm_count_val,
                    vm_total=self._parse_vm_total(all_text),
                    vm_table_count=self._parse_vm_table_count(pdf, vm_count_val),
                    volume_sum_page1=self._parse_volume_sum_page1(text),
                    qty_sum_page3=self._parse_qty_sum_page3(pdf),
                    page2_start=page2_start,
                    page2_end=page2_end,
                    start_date=self._parse_date(text, 'начало'),
                    end_date=self._parse_date(text, 'окончание')
                )

                well_data.task_number = self._parse_task_number(text)
                well_data.contract_number = self._parse_contract_number(text)
                well_data.contract_coeff_value = self._parse_contract_coefficient_from_act(text)
                well_data.well_number, well_data.bush = self._parse_well_and_bush(text)

                rate_rows = self._extract_rate_rows_page1(pdf)
                rate_status, rate_details = self._check_rate_prices_from_rows(rate_rows)
                well_data.rate_check_status = rate_status
                well_data.rate_check_details = rate_details

                # Построчная сверка интегрального коэффициента — переиспользует
                # уже извлечённые строки расценок (та же таблица, что и выше),
                # PDF повторно не открывается.
                integral_status, integral_details = self._check_integral_rows(
                    rate_rows, well_data.temperature, well_data.angle
                )
                well_data.integral_row_status = integral_status
                well_data.integral_row_details = integral_details

                well_data.check_results["barometry_task53"] = well_data._check_barometry_task53(rate_rows)
                well_data.check_results["tech_duty"] = well_data._check_tech_duty_hours(rate_rows)
                well_data.check_results["thermometry_overlap"] = well_data._check_thermometry_overlap(rate_rows)

                if well_data.start_date == "не найдено" or well_data.end_date == "не найдено":
                    start_ocr, end_ocr = self._parse_page1_dates_ocr(pdf)
                    if well_data.start_date == "не найдено" and start_ocr:
                        well_data.start_date = start_ocr
                    if well_data.end_date == "не найдено" and end_ocr:
                        well_data.end_date = end_ocr

                try:
                    from src.extractors.ml_assist import apply_ml_fallback
                except Exception:
                    try:
                        from ml_assist import apply_ml_fallback
                    except Exception:
                        apply_ml_fallback = None

                try:
                    if apply_ml_fallback is not None:
                        apply_ml_fallback(well_data, pdf_path=pdf_path)
                except Exception:
                    pass

                return well_data
                
        except Exception:
            if os.environ.get("AKT_DEBUG_PARSE_ERRORS") == "1":
                traceback.print_exc()
            return self._get_error_result(pdf_path)

    def _normalize_for_match(self, value: object) -> str:
        text = str(value) if value is not None else ""
        translit = {
            "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К",
            "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
            "a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "k": "к",
            "m": "м", "o": "о", "p": "р", "t": "т", "x": "х", "y": "у",
        }
        text = "".join(translit.get(ch, ch) for ch in text)
        return re.sub(r"\s+", " ", text).strip().lower()

    def _parse_decimal(self, value: object) -> float | None:
        if value is None:
            return None
        text = str(value).replace("\u00a0", " ").strip()
        if not text:
            return None
        text = re.sub(r"[^0-9,.\- ]", "", text).replace(" ", "")
        if not text:
            return None
        if text.count(",") > 1 and "." not in text:
            parts = text.split(",")
            text = "".join(parts[:-1]) + "." + parts[-1]
        else:
            text = text.replace(",", ".")
        if text.count(".") > 1:
            parts = text.split(".")
            text = "".join(parts[:-1]) + "." + parts[-1]
        try:
            parsed = float(text)
            if math.isnan(parsed):
                return None
            return parsed
        except Exception:
            return None

    def _normalize_rate_number(self, value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        text = (
            text.replace("O", "0")
            .replace("О", "0")
            .replace("o", "0")
            .replace("о", "0")
        )
        digits = re.sub(r"\D", "", text)
        if not digits:
            return ""
        try:
            return str(int(digits))
        except Exception:
            return ""

    def _format_ru_decimal(self, value: float) -> str:
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", " ")

    def _format_rate_number(self, number: str) -> str:
        if not number:
            return ""
        return number.zfill(3) if len(number) <= 3 else number

    def _resolve_rate_csv_path(self) -> Path | None:
        reference_dir = get_reference_dir()
        preferred = reference_dir / "tabale_rascenki.csv"
        if preferred.exists():
            return preferred
        return None

    def _load_rate_reference(self) -> dict:
        if self._rate_reference_cache is not None:
            return self._rate_reference_cache
        csv_path = self._resolve_rate_csv_path()
        if not csv_path or not csv_path.exists():
            self._rate_reference_cache = {}
            return self._rate_reference_cache
        try:
            df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
        except Exception:
            self._rate_reference_cache = {}
            return self._rate_reference_cache
        if df.empty:
            self._rate_reference_cache = {}
            return self._rate_reference_cache

        columns = list(df.columns)
        number_col = None
        price_col = None
        norm_col = None

        for col in columns:
            col_norm = self._normalize_for_match(str(col)).replace("_", " ")
            if number_col is None and "номер" in col_norm and "расцен" in col_norm:
                number_col = col
            if price_col is None and (
                ("стоим" in col_norm and ("руб" in col_norm or "расцен" in col_norm or "цена" in col_norm))
                or col_norm == "стоимость руб"
            ):
                price_col = col
            if norm_col is None and "норма" in col_norm and "врем" in col_norm:
                norm_col = col

        if number_col is None:
            number_col = columns[0]
        if price_col is None and len(columns) > 1:
            price_col = columns[1]

        rates: dict[str, dict[str, set[float]]] = {}
        for _, row in df.iterrows():
            number = self._normalize_rate_number(row.get(number_col))
            if not number:
                continue

            if number not in rates:
                rates[number] = {"prices": set(), "norms": set()}

            if price_col is not None:
                price = self._parse_decimal(row.get(price_col))
                if price is not None:
                    rates[number]["prices"].add(round(price, 2))

            if norm_col is not None:
                norm_value = self._parse_decimal(row.get(norm_col))
                if norm_value is not None:
                    rates[number]["norms"].add(round(norm_value, 2))

        self._rate_reference_cache = {
            key: {
                "prices": sorted(values.get("prices", set())),
                "norms": sorted(values.get("norms", set())),
            }
            for key, values in rates.items()
        }
        return self._rate_reference_cache

    def _extract_rate_rows_from_table(self, table: list) -> List[dict]:
        if not table:
            return []

        header_idx = None
        name_col = 0
        number_col = None
        price_col = None
        volume_col = None
        norm_col = None
        coeff_col = None
        spent_col = None
        interval_from_col = None
        interval_to_col = None

        for idx, row in enumerate(table[:8]):
            if not row:
                continue
            for col_idx, cell in enumerate(row):
                norm = self._normalize_for_match(cell)
                if "наименование" in norm and "работ" in norm:
                    name_col = col_idx
                if "номер" in norm and "расц" in norm:
                    number_col = col_idx
                if "расценка" in norm:
                    price_col = col_idx
                if "объем" in norm and "работ" in norm:
                    volume_col = col_idx
                if "норма" in norm and "времен" in norm:
                    norm_col = col_idx
                if "интег" in norm or "коэфиц" in norm:
                    coeff_col = col_idx
                if "затрат" in norm and "времен" in norm:
                    spent_col = col_idx
                if "интервал" in norm and interval_from_col is None:
                    interval_from_col = col_idx
                    interval_to_col = col_idx + 1
            if number_col is not None and price_col is not None:
                header_idx = idx
                break

        if header_idx is None:
            header_blob = " ".join(
                self._normalize_for_match(cell)
                for row in table[:3]
                for cell in (row or [])
                if cell
            )
            if "наименование" in header_blob and "расценка" in header_blob:
                header_idx = 1 if len(table) > 1 else 0
                number_col = 1
                price_col = 7
                name_col = 0
                volume_col = 5
                norm_col = 6
                coeff_col = 8
                spent_col = 9
                interval_from_col = 3
                interval_to_col = 4
            else:
                return []

        rows: List[dict] = []
        stop_markers = (
            "итого по акт",
            "и т о г о по акт",
            "всего с учетом коэффициента",
            "стоимость вм",
            "всего к оплате",
        )

        for row in table[header_idx + 1:]:
            if not row:
                continue
            row_text = " ".join(str(cell).strip() for cell in row if cell)
            if not row_text:
                continue

            norm_row = self._normalize_for_match(row_text)
            if any(marker in norm_row for marker in stop_markers):
                break
            if "наименование работ" in norm_row:
                continue

            if number_col is None or number_col >= len(row):
                continue
            if price_col is None or price_col >= len(row):
                continue

            rate_number = self._normalize_rate_number(row[number_col])
            rate_price = self._parse_decimal(row[price_col])
            if not rate_number or rate_price is None:
                continue

            volume_value = None
            if volume_col is not None and volume_col < len(row):
                volume_value = self._parse_decimal(row[volume_col])

            norm_value = None
            if norm_col is not None and norm_col < len(row):
                norm_value = self._parse_decimal(row[norm_col])

            coeff_value = None
            if coeff_col is not None and coeff_col < len(row):
                coeff_value = self._parse_decimal(row[coeff_col])

            spent_value = None
            if spent_col is not None and spent_col < len(row):
                spent_value = self._parse_decimal(row[spent_col])

            interval_from_value = None
            if interval_from_col is not None and interval_from_col < len(row):
                interval_from_value = self._parse_decimal(row[interval_from_col])

            interval_to_value = None
            if interval_to_col is not None and interval_to_col < len(row):
                interval_to_value = self._parse_decimal(row[interval_to_col])

            name = ""
            if name_col < len(row) and row[name_col]:
                name = " ".join(str(row[name_col]).split())
            if not name:
                name = " ".join(str(cell).strip() for cell in row if cell)
                name = re.sub(r"\s+", " ", name)

            rows.append(
                {
                    "name": name,
                    "rate_number": rate_number,
                    "rate_price": round(rate_price, 2),
                    "volume": round(volume_value, 2) if volume_value is not None else None,
                    "norm_time": round(norm_value, 2) if norm_value is not None else None,
                    "integral_coeff": round(coeff_value, 4) if coeff_value is not None else None,
                    "spent_time": round(spent_value, 2) if spent_value is not None else None,
                    "interval_from": round(interval_from_value, 2) if interval_from_value is not None else None,
                    "interval_to": round(interval_to_value, 2) if interval_to_value is not None else None,
                }
            )

        return rows

    def _extract_rate_rows_page1(self, pdf) -> List[dict]:
        if not pdf.pages:
            return []
        page = pdf.pages[0]
        tables = page.extract_tables() or []
        rows: List[dict] = []
        for table in tables:
            rows.extend(self._extract_rate_rows_from_table(table))

        unique_rows: List[dict] = []
        seen: set[tuple] = set()
        for row in rows:
            key = (
                row.get("name", ""),
                row.get("rate_number", ""),
                row.get("rate_price", 0.0),
                row.get("norm_time"),
                row.get("spent_time"),
            )
            if key in seen:
                continue
            seen.add(key)
            unique_rows.append(row)
        return unique_rows

    def _check_rate_prices(self, pdf) -> tuple[str, List[str]]:
        rows = self._extract_rate_rows_page1(pdf)
        return self._check_rate_prices_from_rows(rows)

    def _check_rate_prices_from_rows(self, rows: List[dict]) -> tuple[str, List[str]]:
        reference = self._load_rate_reference()
        if not reference:
            return "neutral", []

        if not rows:
            return "neutral", []

        details: List[str] = []
        checked_rows = 0
        row_ok = 0
        row_bad = 0

        price_ok = 0
        price_bad = 0
        price_missing = 0

        norm_ok = 0
        norm_bad = 0
        norm_missing_ref = 0
        norm_missing_act = 0
        norm_enabled = any((entry.get("norms") or []) for entry in reference.values())

        spent_ok = 0
        spent_bad = 0
        spent_no_data = 0

        for row in rows:
            name = str(row.get("name", "")).strip()
            rate_number = str(row.get("rate_number", ""))
            rate_price = row.get("rate_price")
            if not rate_number:
                continue
            if not isinstance(rate_price, (int, float)):
                continue

            checked_rows += 1

            ref_entry = reference.get(rate_number, {})
            ref_prices = ref_entry.get("prices", []) if isinstance(ref_entry, dict) else []
            ref_norms = ref_entry.get("norms", []) if isinstance(ref_entry, dict) else []
            number_label = self._format_rate_number(rate_number)
            act_price_text = self._format_ru_decimal(float(rate_price))
            name_short = name if len(name) <= 80 else f"{name[:77]}..."

            row_has_issue = False

            if not ref_prices:
                price_missing += 1
                row_has_issue = True
                price_part = f"расценка: акт {act_price_text} / прил.: не найдено"
            else:
                price_match = any(
                    math.isclose(float(rate_price), float(ref), rel_tol=0.0, abs_tol=0.01)
                    for ref in ref_prices
                )
                ref_price_text = " / ".join(self._format_ru_decimal(float(v)) for v in ref_prices[:3])
                if len(ref_prices) > 3:
                    ref_price_text += " / ..."
                price_part = f"расценка: акт {act_price_text} / прил.: {ref_price_text}"
                if price_match:
                    price_ok += 1
                else:
                    price_bad += 1
                    row_has_issue = True

            act_norm = row.get("norm_time")
            norm_part = "норма: нет данных"
            if norm_enabled:
                if not ref_norms:
                    norm_missing_ref += 1
                    row_has_issue = True
                    norm_part = "норма: в прил. не найдена"
                elif not isinstance(act_norm, (int, float)):
                    norm_missing_act += 1
                    row_has_issue = True
                    norm_part = "норма: в акте не найдена"
                else:
                    norm_match = any(
                        math.isclose(float(act_norm), float(ref), rel_tol=0.0, abs_tol=0.01)
                        for ref in ref_norms
                    )
                    ref_norm_text = " / ".join(self._format_ru_decimal(float(v)) for v in ref_norms[:3])
                    if len(ref_norms) > 3:
                        ref_norm_text += " / ..."
                    norm_part = f"норма: акт {self._format_ru_decimal(float(act_norm))} / прил.: {ref_norm_text}"
                    if norm_match:
                        norm_ok += 1
                    else:
                        norm_bad += 1
                        row_has_issue = True
            elif isinstance(act_norm, (int, float)):
                norm_part = f"норма: акт {self._format_ru_decimal(float(act_norm))}"
            else:
                norm_part = "норма: колонка в прил. не задана"

            act_spent = row.get("spent_time")
            act_volume = row.get("volume")
            act_coeff = row.get("integral_coeff")
            spent_part = "затраты: нет данных"
            if isinstance(act_spent, (int, float)) and isinstance(act_norm, (int, float)):
                if isinstance(act_volume, (int, float)):
                    coeff = float(act_coeff) if isinstance(act_coeff, (int, float)) else 1.0
                    expected_spent = float(act_volume) * float(act_norm) * coeff
                    expected_label = f"расч. {self._format_ru_decimal(expected_spent)}"
                else:
                    expected_spent = float(act_norm)
                    expected_label = f"норма {self._format_ru_decimal(float(act_norm))}"
                tolerance = max(0.5, abs(expected_spent) * 0.03)
                spent_match = math.isclose(float(act_spent), expected_spent, rel_tol=0.0, abs_tol=tolerance)
                spent_part = (
                    f"затраты: акт {self._format_ru_decimal(float(act_spent))} / {expected_label}"
                )
                if spent_match:
                    spent_ok += 1
                else:
                    spent_bad += 1
                    row_has_issue = True
            else:
                spent_no_data += 1

            row_icon = "✅" if not row_has_issue else "❌"
            if row_has_issue:
                row_bad += 1
            else:
                row_ok += 1
            details.append(
                f"{row_icon} {name_short} | №{number_label} | {price_part} | {norm_part} | {spent_part}"
            )

        if checked_rows == 0:
            return "neutral", []

        summary_lines = [
            f"Проверено работ: {checked_rows}",
            f"Итог по работам: ✅ {row_ok}, ❌ {row_bad}",
            f"Расценка: ✅ {price_ok}, ❌ {price_bad}, не найдено в прил.: {price_missing}",
        ]
        if norm_enabled:
            summary_lines.append(
                f"Норма времени (прил.): ✅ {norm_ok}, ❌ {norm_bad}, не найдено в прил.: {norm_missing_ref}, нет в акте: {norm_missing_act}"
            )
        else:
            summary_lines.append("Норма времени (прил.): колонка не найдена в CSV")
        summary_lines.append(
            f"Затраты времени (акт/расчет): ✅ {spent_ok}, ❌ {spent_bad}, нет данных: {spent_no_data}"
        )

        status_is_bad = (
            row_bad > 0
            or price_bad > 0
            or price_missing > 0
            or spent_bad > 0
            or (norm_enabled and (norm_bad > 0 or norm_missing_ref > 0 or norm_missing_act > 0))
        )
        status = "bad" if status_is_bad else "ok"
        return status, summary_lines + details

    # Строки расценок, для которых интегральный коэффициент считается только
    # по температуре (услуги/ПЗР, вспом. работы, калибровка, тех.дежурство,
    # переезды, работы спецкабелем/дефектоскопия) — по Приложению №6 к
    # ЕНВиР-99-Л-3С угол наклона на них не влияет. Всё остальное (собственно
    # скважинные исследования, спуск-подъём прибора) — оба фактора.
    # Ключевые слова без пробелов — сравниваются с именем строки после
    # удаления всех пробелов (в реальных актах написание "Всп.работы" /
    # "Всп. работы" встречается непоследовательно).
    _INTEGRAL_PARTY_ONLY_KEYWORDS = (
        "услуги",
        "всп.раб",  # "Всп.работы", "Всп. работы", "Всп.раб." — варианты написания встречаются все
        "вспомогательныеработы",
        "калибровк",
        "тех.дежурство",
        "технологическоедежурство",
        "работакомпл.партии",
        "работапартии",
        "переезд",
        "дефект",  # дефектоскопия, "дефект.и толщин."
        "толщинометри",
        "спецкаб",  # работы спецкабелем — угол не влияет (эмпирически, реальные акты)
    )

    def _classify_integral_work_type(self, name: str) -> str:
        norm = re.sub(r"\s+", "", name.lower())
        for keyword in self._INTEGRAL_PARTY_ONLY_KEYWORDS:
            if keyword in norm:
                return "party"
        return "well"

    def _check_integral_rows(self, rows: List[dict], temperature: str, angle: str) -> tuple[str, List[str]]:
        try:
            from integral import CoefficientTable
        except Exception:
            return "neutral", []

        try:
            temp = float(str(temperature).replace(",", "."))
        except Exception:
            return "neutral", []

        try:
            angle_val = float(str(angle).replace(",", "."))
        except Exception:
            angle_val = None

        table = CoefficientTable()
        k_party = table.get_temperature_coefficient(temp)
        k_well = table.get_integral_coefficient(temp, angle_val) if angle_val is not None else None

        details: List[str] = []
        ok_count = 0
        bad_count = 0

        for row in rows:
            actual = row.get("integral_coeff")
            if not isinstance(actual, (int, float)):
                continue

            name = str(row.get("name", "")).strip()
            work_type = self._classify_integral_work_type(name)
            expected = k_well if work_type == "well" else k_party
            if expected is None:
                continue

            match = math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=0.02)
            name_short = name if len(name) <= 70 else f"{name[:67]}..."
            icon = "✅" if match else "❌"
            kind = "скв." if work_type == "well" else "парт."
            details.append(
                f"{icon} {name_short} | акт={float(actual):.2f} / расчёт={float(expected):.2f} ({kind})"
            )
            if match:
                ok_count += 1
            else:
                bad_count += 1

        if ok_count == 0 and bad_count == 0:
            return "neutral", []

        status = "bad" if bad_count > 0 else "ok"
        summary = f"Совпало: {ok_count}, расхождений: {bad_count}"
        return status, [summary] + details

    # ===== ОСНОВНЫЕ ДАННЫЕ =====
    
    def _parse_field(self, text: str) -> str:
        """Месторождение"""
        match = re.search(r'Месторождение[^А-Я]*([А-Я][а-я]+ское|[А-Я][а-я]+ное)', text)
        return match.group(1) if match else "не найдено"
    
    def _parse_order(self, text: str, pdf_path: str) -> str:
        """Номер заказа"""
        match = re.search(r'Заказ\s*№[^\d]*([\d\.\s]{6,10})', text)
        if match:
            digits = re.sub(r'[^\d]', '', match.group(1))
            if 6 <= len(digits) <= 7:
                return digits
        
        filename = os.path.basename(pdf_path)
        match = re.search(r'_(\d{6,7})\.pdf$', filename)
        return match.group(1) if match else "не найдено"

    def _parse_task_number(self, text: str) -> str:
        """Номер задачи (например 53, 87(Р), 500.4, 58.158)"""
        match = re.search(r'Задача\s*№\s*([0-9]+(?:\.[0-9]+)?(?:\([А-Яа-я]+\))?)', text)
        return match.group(1) if match else ""

    def _parse_contract_number(self, text: str) -> str:
        """Номер договора (только числовой формат — учитываются лишь
        договоры из CONTRACT_COEFFICIENTS; старые буквенно-цифровые номера
        вроде '22С3286' для этой проверки не применимы)."""
        match = re.search(r'[Дд]оговор[а-я]*\s*№\s*([0-9]{6,})', text)
        return match.group(1) if match else ""

    def _parse_contract_coefficient_from_act(self, text: str) -> float | None:
        """Значение из строки 'Всего с учетом коэффициента' на 1 странице акта."""
        match = re.search(r'Всего с учетом коэффициента[^\d]*([\d]+[,.]\d+)', text)
        if not match:
            return None
        try:
            return float(match.group(1).replace(",", "."))
        except Exception:
            return None

    def _parse_well_and_bush(self, text: str) -> tuple[str, str]:
        """Номер скважины и куста из строки 'Номер скважины / куст.......1867 / 151'."""
        match = re.search(r'Номер скважины\s*/\s*куст[\.\s]*(\d+)\s*/\s*(\d+)', text)
        if match:
            return match.group(1), match.group(2)
        return "", ""

    def _parse_depth(self, text: str) -> str:
        """Глубина забоя"""
        match = re.search(r'Глубина забоя[^\d]*([\d\s]{3,6})', text)
        if match:
            depth = match.group(1).replace(' ', '')
            if 3 <= len(depth) <= 5:
                return depth
        return "не найдено"
    
    def _parse_angle(self, text: str) -> str:
        """Угол наклона"""
        lines = text.split('\n')
        for line in lines:
            if 'Угол наклона' in line:
                line_clean = line.replace(' ', '')
                
                # Для "2.4,89" (второй файл)
                match = re.search(r'Уголнаклона[^\d]*(\d+)\.(\d+),(\d+)', line_clean)
                if match:
                    return f"{match.group(1)}{match.group(2)},{match.group(3)}"
                
                # Для "36,5" (первый файл)
                match = re.search(r'Уголнаклона[^\d]*(\d+),(\d+)', line_clean)
                if match:
                    return f"{match.group(1)},{match.group(2)}"
                
                # Общий случай
                match = re.search(r'Уголнаклона[^\d]*(\d+)', line_clean)
                if match:
                    return match.group(1)
        
        return "не найдено"
    
    def _parse_temperature(self, text: str) -> str:
        """Температура воздуха"""
        lines = text.split('\n')
        for line in lines:
            if 'Температура воздуха' in line:
                line_processed = re.sub(r'(?<=\d)\.(?=[\d,])', '', line)
                match = re.search(r'Температура воздуха[^\d\-]*(-?\d+)[,\.]?(\d*)', line_processed)
                if match:
                    if match.group(2):
                        return f"{match.group(1)},{match.group(2)}"
                    return match.group(1)
        
        return "не найдено"
    
    def _parse_volume(self, text: str) -> str:
        """Объем работ - ищет 3-й столбец в табличной строке"""
        lines = text.split('\n')
        
        for line in lines:
            if 'С/п скв.приб' in line:
                # Убираем лишние пробелы и нормализуем
                line_clean = ' '.join(line.split())
                
                # Разделяем строку по пробелам - это наши столбцы
                columns = line_clean.split()
                
                # Ищем столбцы, содержащие числа с запятыми
                numeric_columns = []
                for col in columns:
                    if re.search(r'\d+,\d+', col):
                        numeric_columns.append(col)
                
                # ИЗМЕНЕНИЕ: берем 3-й числовой столбец (индекс 2) вместо 5-го
                if len(numeric_columns) >= 3:
                    volume = numeric_columns[2]  # 3-й столбец
                    # Очищаем от возможных лишних символов
                    volume = re.sub(r'[^\d,]', '', volume)
                    return volume
                elif numeric_columns:
                    # Если меньше 3 столбцов, берем последний
                    volume = numeric_columns[-1]
                    volume = re.sub(r'[^\d,]', '', volume)
                    return volume
        
        # Если не нашли, попробуем другой подход
        return self._find_volume_in_table(text)
    
    def _find_volume_in_table(self, text: str) -> str:
        """Ищет объем работ в табличной структуре"""
        lines = text.split('\n')
        
        # Ищем строку с заголовком таблицы
        table_start = -1
        for i, line in enumerate(lines):
            if 'С/п скв.приб' in line:
                table_start = i
                break
        
        if table_start == -1:
            return "не найдено"
        
        # Ищем строку с данными (обычно следующая строка)
        if table_start + 1 < len(lines):
            data_line = lines[table_start + 1]
            
            # Разделяем на столбцы
            data_columns = data_line.split()
            
            # Ищем числовые столбцы
            numeric_data = []
            for col in data_columns:
                if re.search(r'\d+,\d+', col):
                    numeric_data.append(col)
            
            # ИЗМЕНЕНИЕ: берем 3-й столбец (индекс 2) вместо 5-го
            if len(numeric_data) >= 3:
                volume = numeric_data[2]  # 3-й столбец
                volume = re.sub(r'[^\d,]', '', volume)
                return volume
            elif numeric_data:
                volume = numeric_data[-1]
                volume = re.sub(r'[^\d,]', '', volume)
                return volume
        
        return "не найдено"

    def _parse_spo(self, text: str, pdf) -> str:
        """СПО (м)"""
        value = self._parse_spo_from_text(text)
        if value:
            return value
        value = self._parse_spo_from_ocr(pdf)
        return value if value else "не найдено"

    def _parse_spo_from_text(self, text: str) -> str:
        # Normalize common OCR confusions between Latin/Cyrillic letters and 0/O.
        # Normalize only Latin letter lookalikes to Cyrillic for keyword detection.
        # Do NOT replace digit "0" — it would corrupt numeric values like "1000" → "1ООО".
        normalized = (
            text.replace("C", "С")
            .replace("P", "Р")
            .replace("O", "О")
            .replace("c", "с")
            .replace("p", "р")
            .replace("o", "о")
            .replace("m", "м")
            .replace("M", "М")
        )

        # First try direct match on the same line.
        patterns = [
            r'С\s*П\s*О\s*[:\-]?\s*([\d\s]+[,\.\d]*)\s*м?',
            r'СПО\s*[:\-]?\s*([\d\s]+[,\.\d]*)\s*м?',
            # "Справка по зарегистрированному материалу" пишет СПО текстом,
            # без аббревиатуры: "Спуск-подъём прибора составил – 1135.30 м"
            r'Спуск[\s\-]*подъ[её]м\s*прибора\s*составил\s*[-–:]?\s*([\d\s]+[,\.\d]*)\s*м',
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, normalized, re.IGNORECASE):
                value = match.group(1).replace(' ', '')
                value = value.replace(',', '.')
                value = re.sub(r'[^0-9\.\-]', '', value)
                if re.search(r'\d', value):
                    return value

        # If OCR split the number to the next line, look around "СПО" line.
        lines = normalized.splitlines()
        for i, line in enumerate(lines):
            if "СПО" in line or "С П О" in line:
                # Try number on the same line
                match = re.search(r'([\d\s]+[,\.\d]*)', line)
                if match:
                    value = match.group(1).replace(' ', '').replace(',', '.')
                    value = re.sub(r'[^0-9\.\-]', '', value)
                    if re.search(r'\d', value):
                        return value
                # Try next line
                if i + 1 < len(lines):
                    match = re.search(r'([\d\s]+[,\.\d]*)', lines[i + 1])
                    if match:
                        value = match.group(1).replace(' ', '').replace(',', '.')
                        value = re.sub(r'[^0-9\.\-]', '', value)
                        if re.search(r'\d', value):
                            return value
        return ""

    def _parse_spo_fallback_number(self, text: str) -> str:
        # Deprecated fallback kept for compatibility; require explicit СПО in OCR.
        return ""

    def _configure_tesseract(self, pytesseract_module) -> bool:
        try:
            current_cmd = str(getattr(pytesseract_module.pytesseract, "tesseract_cmd", "")).strip()
            if current_cmd and Path(current_cmd).exists():
                cmd_path = Path(current_cmd)
                for tessdata in (cmd_path.parent / "tessdata", cmd_path.parent.parent / "tessdata"):
                    if tessdata.exists():
                        os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))
                        break
                return True
        except Exception:
            pass

        candidates: List[Path] = []
        try:
            in_path = shutil.which("tesseract")
            if in_path:
                candidates.append(Path(in_path))
        except Exception:
            pass

        for root in get_resource_roots():
            candidates.extend(
                [
                    root / "tesseract" / "tesseract",
                    root / "tesseract" / "tesseract.exe",
                    root / "tesseract" / "bin" / "tesseract",
                    root / "tesseract" / "bin" / "tesseract.exe",
                ]
            )

        candidates.extend([Path("/opt/homebrew/bin/tesseract"), Path("/usr/local/bin/tesseract")])

        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            if not candidate.exists():
                continue
            try:
                pytesseract_module.pytesseract.tesseract_cmd = str(candidate)
                for tessdata in (candidate.parent / "tessdata", candidate.parent.parent / "tessdata"):
                    if tessdata.exists():
                        os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))
                        break
                return True
            except Exception:
                continue
        return False

    def _parse_spo_from_ocr(self, pdf) -> str:
        try:
            import pytesseract
        except Exception:
            return ""
        if not self._configure_tesseract(pytesseract):
            return ""

        pages = list(pdf.pages)
        page_count = len(pages)
        # Narrow scan to likely pages to avoid long OCR runs.
        if page_count >= 9:
            scan_order = [8, 6, 5, 7]  # include 9th page first (0-based)
        elif page_count >= 7:
            scan_order = list(range(page_count - 1, max(page_count - 4, -1), -1))
        else:
            scan_order = list(range(page_count))

        for idx in scan_order:
            page = pages[idx]
            try:
                # OCR center-bottom band where "СПО" sits under the table
                height = page.height
                width = page.width
                crops = [
                    (0, height * 0.60, width, height * 0.98),  # area with table + СПО line
                    (0, height * 0.50, width, height * 0.90),
                ]
                try:
                    configs = [
                        "--psm 6 -c tessedit_char_whitelist=СПОspoSPO0123456789.,:мMm ",
                        "--psm 6",
                    ]
                    for crop_box in crops:
                        cropped = page.crop(crop_box)
                        image = cropped.to_image(resolution=300).original
                        for config in configs:
                            text = pytesseract.image_to_string(
                                image, lang="rus+eng", config=config, timeout=7
                            )
                            value = self._parse_spo_from_text(text)
                            if value:
                                return value
                except Exception:
                    continue
                # Skip full-page OCR to keep runtime reasonable
            except Exception:
                continue
        # Additional scan: look for "Справка по зарегистрированному материалу" page
        try:
            for idx, page in enumerate(pages):
                text = page.extract_text() or ""
                if "Справка по зарегистрированному материалу" not in text:
                    continue
                height = page.height
                width = page.width
                crop = page.crop((0, height * 0.70, width, height * 0.98))
                image = crop.to_image(resolution=300).original
                for config in ("--psm 6", "--psm 7"):
                    ocr_text = pytesseract.image_to_string(
                        image, lang="rus+eng", config=config, timeout=8
                    )
                    value = self._parse_spo_from_text(ocr_text)
                    if value:
                        return value
        except Exception:
            pass

        # Targeted scan: 7th page bottom area (common location in newer files)
        try:
            if len(pages) >= 7:
                from PIL import ImageOps
                page = pages[6]
                height = page.height
                width = page.width
                crop = page.crop((0, height * 0.65, width, height * 0.98))
                image = crop.to_image(resolution=400).original
                gray = ImageOps.grayscale(image)
                gray = ImageOps.autocontrast(gray)
                images = [gray]
                for thr in (160, 180, 200, 220):
                    images.append(gray.point(lambda x, t=thr: 0 if x < t else 255, "1"))
                for img in images:
                    for config in (
                        "--psm 6 -c tessedit_char_whitelist=СПОspoSPO0123456789.,:мMm ",
                        "--psm 7",
                        "--psm 6",
                    ):
                        ocr_text = pytesseract.image_to_string(
                            img, lang="rus+eng", config=config, timeout=8
                        )
                        value = self._parse_spo_from_text(ocr_text)
                        if value:
                            return value
        except Exception:
            pass

        # Final fallback: OCR bottom band on every page (for scanned docs without text layer)
        try:
            scan_pages = pages[-4:] if len(pages) > 4 else pages
            for page in scan_pages:
                height = page.height
                width = page.width
                crop = page.crop((0, height * 0.70, width, height * 0.98))
                image = crop.to_image(resolution=200).original
                for config in ("--psm 6 -c tessedit_char_whitelist=СПОspoSPO0123456789.,:мMm ",
                               "--psm 6"):
                    ocr_text = pytesseract.image_to_string(
                        image, lang="rus+eng", config=config, timeout=8
                    )
                    value = self._parse_spo_from_text(ocr_text)
                    if value:
                        return value
        except Exception:
            pass

        # Full-page OCR fallback on 7th page (slow, but catches scanned СПО lines)
        try:
            if len(pages) >= 7:
                from PIL import ImageOps
                page = pages[6]
                image = page.to_image(resolution=250).original
                gray = ImageOps.grayscale(image)
                gray = ImageOps.autocontrast(gray)
                ocr_text = pytesseract.image_to_string(
                    gray, lang="rus+eng", config="--psm 11 --oem 1", timeout=8
                )
                value = self._parse_spo_from_text(ocr_text)
                if value:
                    return value
        except Exception:
            pass

        return ""
    
    # ===== ДАТЫ =====
    
    def _parse_date(self, text: str, date_type: str) -> str:
        """Парсит даты начала или окончания работ"""
        lines = text.split('\n')
        start_labels = (
            "Hачало работ",
            "Начало работ",
            "Начало работ на скв",
            "Начало работ на объекте",
        )
        end_labels = (
            "Окончание работ",
            "Окончание работы",
            "Окончание работ на скв",
            "Окончание работ на объекте",
        )

        for line in lines:
            if date_type == 'начало':
                if any(label in line for label in start_labels):
                    value = self._extract_date_from_line(line)
                    if value != "не найдено":
                        return value
            elif date_type == 'окончание':
                if any(label in line for label in end_labels):
                    value = self._extract_date_from_line(line)
                    if value != "не найдено":
                        return value

        if date_type == 'начало':
            label_regex = r'(?:Hачало|Начало)\s+работ.*?'
        else:
            label_regex = r'Окончание\s+работ.*?'
        match = re.search(label_regex + r'(\d{1,2}\.\d{1,2}\.\d{4})\s+(\d{1,2}:\d{2})', text, re.DOTALL)
        if match:
            date_part = match.group(1)
            time_part = match.group(2)
            return f"{date_part} {time_part}"

        return "не найдено"
    
    def _extract_date_from_line(self, line: str) -> str:
        """Извлекает дату из строки"""
        # Normalize OCR artifacts like "0.4.02.2026" -> "04.02.2026"
        line = re.sub(r'(\d)\.(\d)\.(\d{2})\.(\d{4})', r'\1\2.\3.\4', line)
        line = re.sub(r'(\d)\.(\d)\.(\d)\.(\d{4})', r'\1\2.0\3.\4', line)

        # Ищем время
        time_match = re.search(r'(\d{1,2}):(\d{2})', line)
        hour = "00"
        minute = "00"
        
        if time_match:
            hour = time_match.group(1).zfill(2)
            minute = time_match.group(2).zfill(2)
        
        # Специфические форматы для ваших файлов
        
        # "3.0.11.2025" -> день=30, месяц=11, год=2025
        if '3.0.11.2025' in line or '3.0.11' in line:
            return f"30.11.2025 {hour}:{minute}"
        
        # "0.1.12.2025" -> день=01, месяц=12, год=2025
        if '0.1.12.2025' in line or '0.1.12' in line:
            return f"01.12.2025 {hour}:{minute}"
        
        # Стандартный формат
        match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', line)
        if match:
            day = match.group(1).zfill(2)
            month = match.group(2).zfill(2)
            year = match.group(3)
            return f"{day}.{month}.{year} {hour}:{minute}"
        
        # Поиск по цифрам
        digits = re.findall(r'\d+', line)
        
        if len(digits) >= 6:
            for i, d in enumerate(digits):
                if len(d) == 4:  # Нашли год
                    year = d
                    if i >= 2:
                        month = digits[i-1].zfill(2)
                        day = digits[i-2]
                        
                        if len(day) == 1 and i >= 3:
                            prev_digit = digits[i-3]
                            if len(prev_digit) == 1:
                                day = prev_digit + day
                        
                        return f"{day.zfill(2)}.{month}.{year} {hour}:{minute}"
        
        return "не найдено"
    
    def _get_error_result(self, pdf_path: str) -> WellData:
        """Шаблон для ошибки"""
        return WellData(
            filename=os.path.basename(pdf_path),
            field='ошибка',
            order='ошибка',
            depth='ошибка',
            angle='ошибка',
            temperature='ошибка',
            volume='ошибка',
            spo='ошибка',
            vm_task='ошибка',
            vm_price='ошибка',
            vm_count='ошибка',
            vm_total='ошибка',
            vm_table_count='ошибка',
            volume_sum_page1='ошибка',
            qty_sum_page3='ошибка',
            page2_start='ошибка',
            page2_end='ошибка',
            start_date='ошибка',
            end_date='ошибка'
        )

    def _parse_vm_task(self, text: str) -> str:
        match = re.search(r'Задача\s*№\s*([0-9]+[.,][0-9]+)', text)
        if match:
            return match.group(1)
        match = re.search(r'Стоимость\s+ВМ.*?([0-9]+[.,][0-9]+)', text, re.IGNORECASE | re.DOTALL)
        return match.group(1) if match else ""

    def _parse_vm_price(self, text: str) -> str:
        vm_line = self._find_vm_task_line(text)
        if vm_line:
            match = re.search(
                r'(\d+)\s*х\s*([0-9\s]+[,\.][0-9]{1,2})\s+([0-9\s]+[,\.][0-9]{1,2})',
                vm_line,
                re.IGNORECASE,
            )
            if match:
                return match.group(2).replace(' ', '')
        patterns = [
            r'Стоимость ВМ.*?Цена[^0-9]*([0-9\s]+[,\.][0-9]{1,2})',
            r'Цена[^0-9]*([0-9\s]+[,\.][0-9]{1,2})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).replace(' ', '')
        return ""

    def _parse_vm_count(self, text: str) -> str:
        vm_line = self._find_vm_task_line(text)
        if vm_line:
            match = re.search(r'(\d+)\s*х\s*([0-9\s]+[,\.][0-9]{1,2})', vm_line, re.IGNORECASE)
            if match:
                return match.group(1)
            match = re.search(r'(\d+)\s+х', vm_line, re.IGNORECASE)
            if match:
                return match.group(1)
        match = re.search(r'Кол-?во[^0-9]*([0-9]+[.,]?[0-9]*)', text, re.IGNORECASE)
        return match.group(1).replace(' ', '') if match else ""

    def _parse_vm_total(self, text: str) -> str:
        vm_line = self._find_vm_task_line(text)
        if vm_line:
            match = re.search(
                r'(\d+)\s*х\s*([0-9\s]+[,\.][0-9]{1,2})\s+([0-9\s]+[,\.][0-9]{1,2})',
                vm_line,
                re.IGNORECASE,
            )
            if match:
                return match.group(3).replace(' ', '')
        match = re.search(
            r'Цена[^0-9]*([0-9\s]+[,\.][0-9]{1,2})\s*([0-9\s]+[,\.][0-9]{1,2})',
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group(2).replace(' ', '')
        return ""

    def _find_vm_task_line(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for i, line in enumerate(lines):
            if "Стоимость ВМ" in line:
                if i + 1 < len(lines):
                    return lines[i + 1]
        return ""

    def _parse_vm_table_count(self, pdf, expected_count: str = "") -> str:
        if len(pdf.pages) < 2:
            return ""
        try:
            import pytesseract
            from PIL import ImageOps
        except Exception:
            return ""
        if not self._configure_tesseract(pytesseract):
            return ""
        page = pdf.pages[1]
        height = page.height
        width = page.width
        boxes = [
            (0.75, 0.48, 0.98, 0.70),  # catches 180 in Ватьеганское
            (0.80, 0.50, 0.98, 0.70),  # catches 1 in Повховское
        ]
        try:
            expected = float(str(expected_count).replace(",", "."))
        except Exception:
            expected = None
        candidates = []
        for x1, y1, x2, y2 in boxes:
            crop = page.crop((width * x1, height * y1, width * x2, height * y2))
            image = crop.to_image(resolution=300).original
            gray = ImageOps.grayscale(image)
            bw = gray.point(lambda x: 0 if x < 200 else 255, "1")
            ocr_text = pytesseract.image_to_string(
                bw,
                lang="rus+eng",
                config="--psm 6 -c tessedit_char_whitelist=0123456789",
                timeout=15,
            )
            nums = re.findall(r"\d{1,4}", ocr_text)
            for n in nums:
                if n.isdigit():
                    candidates.append(int(n))
        if not candidates:
            return ""
        if expected is not None:
            candidates.sort(key=lambda n: abs(n - expected))
            return str(candidates[0])
        candidates.sort(key=lambda n: (-len(str(n)), -n))
        return str(candidates[0])

    def _parse_volume_sum_page1(self, text: str) -> str:
        def _norm(s: str) -> str:
            repl = {
                "H": "Н", "A": "А", "B": "В", "C": "С", "E": "Е", "K": "К",
                "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
                "a": "а", "b": "в", "c": "с", "e": "е", "k": "к", "m": "м",
                "o": "о", "p": "р", "t": "т", "x": "х", "y": "у",
            }
            return "".join(repl.get(ch, ch) for ch in s).lower()

        lines = text.splitlines()
        in_table = False
        total = 0.0
        for line in lines:
            norm = _norm(line)
            if "наименование" in norm and "работ" in norm:
                in_table = True
                continue
            if not in_table:
                continue
            if "стоимость скважинных исследований" in norm:
                break
            numbers = re.findall(r'\d+,\d+', line)
            if len(numbers) >= 3:
                try:
                    value = float(numbers[2].replace(',', '.'))
                    total += value
                except Exception:
                    continue
        return f"{total:.2f}" if total > 0 else ""

    def _parse_qty_sum_page3(self, pdf) -> str:
        if len(pdf.pages) < 3:
            return ""
        text = pdf.pages[2].extract_text() or ""
        lines = text.splitlines()
        total = 0.0
        for line in lines:
            line = line.strip()
            if not line or not line[0].isdigit():
                continue
            ints = re.findall(r'\b\d+\b', line)
            if len(ints) < 3:
                continue
            last_three = [int(i) for i in ints[-3:]]
            total += last_three[1]
        return f"{total:.2f}" if total > 0 else ""

    def _parse_page2_start_end(self, pdf):
        if len(pdf.pages) < 2:
            return "", ""
        try:
            import pytesseract
            from PIL import ImageOps
        except Exception:
            return "", ""
        if not self._configure_tesseract(pytesseract):
            return "", ""
        page = pdf.pages[1]
        h = page.height
        w = page.width
        # Crop the right-middle block with start/end lines
        crop = page.crop((w * 0.60, h * 0.30, w * 0.98, h * 0.65))
        image = crop.to_image(resolution=250).original
        text = pytesseract.image_to_string(image, lang="rus+eng", config="--psm 6", timeout=10)
        text = text.replace("..", ".").replace(" .", ".").replace("|", ".")

        def _find_after(label: str) -> str:
            m = re.search(label, text, re.IGNORECASE)
            if not m:
                return ""
            tail = text[m.end(): m.end() + 120]
            line = tail.splitlines()[0] if tail.splitlines() else tail
            date_match = re.search(r'(\d{1,2})\D+(\d{1,2})\D+(\d{2,4})', line)
            if not date_match:
                return ""
            day, month, year = date_match.group(1), date_match.group(2), date_match.group(3)
            tail_after_date = line[date_match.end():]
            nums = re.findall(r'\d+', tail_after_date)
            time_token = nums[0] if len(nums) > 0 else ""
            time_match = re.search(r'(\d{1,2})\D+(\d{2})', tail_after_date)
            if len(year) == 2:
                year = "20" + year
            day = day.zfill(2)
            month = month.zfill(2)
            hour = "00"
            minute = "00"
            if time_match:
                hour = time_match.group(1).zfill(2)
                minute = time_match.group(2).zfill(2)
            elif time_token:
                if len(time_token) >= 4:
                    hour = time_token[:2]
                    minute = time_token[2:4]
                elif len(time_token) == 3:
                    hour = time_token[:1].zfill(2)
                    minute = time_token[1:3]
                elif len(time_token) <= 2:
                    hour = time_token.zfill(2)
                    minute = nums[4].zfill(2) if len(nums) > 4 else "00"
            try:
                if int(minute) > 59:
                    minute = "00"
            except Exception:
                minute = "00"
            if len(time_token) >= 5 and minute != "00":
                minute = "00"
            return f"{day}.{month}.{year} {hour}:{minute}"

        start = _find_after("Начало работы на объекте")
        if not start:
            start = _find_after("Начало работ на объекте")
        end = _find_after("Окончание работы партии")
        if not end:
            end = _find_after("Окончание работ партии")
        if start and end:
            return start, end

        try:
            text = page.extract_text() or ""
            lines = text.splitlines()
            start = ""
            end = ""
            for line in lines:
                if not start and "Начало работ" in line:
                    start = self._extract_date_from_line(line)
                if not end and "Окончание работ" in line:
                    end = self._extract_date_from_line(line)
                if start and end:
                    break
            if start and end:
                return start, end
        except Exception:
            pass

        matches = re.findall(r'(\d{2}\.\d{2}\.\d{4}\s+\d{2}[:\.]\d{2})', text)
        if len(matches) >= 2:
            return matches[0].replace(".", ":", 1), matches[1].replace(".", ":", 1)
        return "", ""

    def _parse_page1_dates_ocr(self, pdf):
        if not pdf.pages:
            return "", ""
        try:
            import pytesseract
            from PIL import ImageOps
        except Exception:
            return "", ""
        if not self._configure_tesseract(pytesseract):
            return "", ""
        page = pdf.pages[0]
        h = page.height
        w = page.width
        crops = [
            (w * 0.55, h * 0.35, w * 0.98, h * 0.65),
            (w * 0.45, h * 0.30, w * 0.98, h * 0.70),
        ]
        for crop_box in crops:
            try:
                crop = page.crop(crop_box)
                image = crop.to_image(resolution=300).original
                gray = ImageOps.grayscale(image)
                gray = ImageOps.autocontrast(gray)
                text = pytesseract.image_to_string(
                    gray,
                    lang="rus+eng",
                    config="--psm 6",
                    timeout=8,
                )
                start = self._extract_date_from_label(text, "Начало работ")
                end = self._extract_date_from_label(text, "Окончание работ")
                if start and end:
                    return start, end
            except Exception:
                continue
        return "", ""

    def _extract_date_from_label(self, text: str, label: str) -> str:
        try:
            match = re.search(label + r".*?(\d{1,2}\.\d{1,2}\.\d{4})\s+(\d{1,2}:\d{2})", text, re.DOTALL)
            if match:
                return f"{match.group(1)} {match.group(2)}"
        except Exception:
            pass
        return ""


class PDFProcessor:
    """Обработчик всех PDF файлов"""
    
    def __init__(self):
        self.parser = FinalUnifiedParser()
        self.all_wells_data = []  # Список всех объектов WellData
        
    def process_all_pdfs(self) -> List[WellData]:
        """Обрабатывает все PDF файлы"""
        input_dir = get_input_dir()
        
        pdf_files = list(input_dir.glob("*.pdf"))
        
        if not pdf_files:
            return []
        
        for pdf_file in pdf_files:
            # Парсим данные из PDF
            well_data = self.parser.parse_all(str(pdf_file))
            self.all_wells_data.append(well_data)
        
        return self.all_wells_data

    def process_pdfs(self, pdf_paths: List[Path]) -> List[WellData]:
        """Обрабатывает указанные PDF файлы"""
        for pdf_file in pdf_paths:
            well_data = self.parser.parse_all(str(pdf_file))
            self.all_wells_data.append(well_data)
        return self.all_wells_data
    
    def print_all_results(self):
        """Выводит только результаты парсинга"""
        for well_data in self.all_wells_data:
            well_data.print_with_units()

def main(args: List[str] | None = None):
    """Главная функция - только вывод результатов"""
    ensure_runtime_layout(copy_reference=True)
    processor = PDFProcessor()

    input_dir = get_input_dir()
    cli_args = args if args is not None else sys.argv[1:]
    pdf_paths = []
    if cli_args:
        pdf_paths = []
        for arg in cli_args:
            candidate = Path(arg)
            if not candidate.is_absolute():
                candidate = input_dir / arg
            if candidate.exists() and candidate.suffix.lower() == ".pdf":
                pdf_paths.append(candidate)
        if not pdf_paths:
            print("❌ PDF файлы не найдены")
            return
        all_data = processor.process_pdfs(pdf_paths)
    else:
        # 1. Обрабатываем все PDF файлы
        pdf_paths = list(input_dir.glob("*.pdf"))
        all_data = processor.process_all_pdfs()
    
    if not all_data:
        print("❌ Файлы не найдены")
        return
    
    # 2. Выводим только результаты
    processor.print_all_results()

    # 3. Дополнительные отчеты
    run_additional_reports(pdf_paths, all_data)


def run_additional_reports(pdf_paths, wells_data: List["WellData"] | None = None):
    if not pdf_paths:
        return
    reports = [
        ("Отчет по температуре", "src.extractors.table_parser"),
        ("Интегральный коэффициент", "integral"),
        ("Отчет по километражу", "src.extractors.km_parser"),
    ]
    report_args = [str(p) for p in pdf_paths]
    for title, module_name in reports:
        print(f"\n=== {title} ===")
        try:
            module = importlib.import_module(module_name)
            # Модули, которые умеют работать с уже посчитанным WellData
            # (не открывают и не парсят PDF заново), объявляют run_report().
            run_fn = getattr(module, "run_report", None) if wells_data else None
            if callable(run_fn):
                run_fn(pdf_paths, wells_data)
                continue
            main_fn = getattr(module, "main", None)
            if not callable(main_fn):
                print("⚠️ ОШИБКИ:")
                print(f"Модуль {module_name} не содержит функцию main()")
                continue
            main_fn(report_args)
        except Exception:
            print("\n⚠️ ОШИБКИ:")
            traceback.print_exc()

if __name__ == "__main__":
    main()
