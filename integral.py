#!/usr/bin/env python3
"""
Модуль для расчета интегрального коэффициента
на основе поправочных коэффициентов из таблицы
"""

import re
import os
import pdfplumber
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
import sys
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.app_paths import ensure_runtime_layout, get_input_dir

@dataclass
class CorrectionCoefficient:
    """Класс для хранения данных о поправочном коэффициенте"""
    category: str
    condition: str
    coefficient: float
    work_type: str
    
    def __str__(self):
        return f"{self.category}: {self.condition} -> {self.coefficient}"

class CoefficientTable:
    """Класс для работы с таблицей поправочных коэффициентов"""
    
    def __init__(self):
        self.coefficients = self._parse_coefficient_table()
    
    def _parse_coefficient_table(self) -> List[CorrectionCoefficient]:
        coefficients = []
        
        # Температурные коэффициенты
        coefficients.extend([
            CorrectionCoefficient("Температура", "от +35°C до -5°C", 1.0, "ПЗР"),
            CorrectionCoefficient("Температура", "от -5°C до -20°C или выше +35°C", 1.17, "ПЗР"),
            CorrectionCoefficient("Температура", "ниже -20°C", 1.34, "ПЗР"),
            CorrectionCoefficient("Температура", "от +35°C до -5°C", 1.0, "Работа_на_скважине"),
            CorrectionCoefficient("Температура", "от -5°C до -20°C или выше +35°C", 1.17, "Работа_на_скважине"),
            CorrectionCoefficient("Температура", "ниже -20°C", 1.34, "Работа_на_скважине"),
            CorrectionCoefficient("Температура", "от +35°C до -5°C", 1.0, "Спуск_подъем"),
            CorrectionCoefficient("Температура", "от -5°C до -20°C или выше +35°C", 1.17, "Спуск_подъем"),
            CorrectionCoefficient("Температура", "ниже -20°C", 1.34, "Спуск_подъем"),
        ])
        
        # Коэффициенты для угла наклона
        coefficients.extend([
            CorrectionCoefficient("Угол наклона", "до 20°", 1.0, "ПЗР"),
            CorrectionCoefficient("Угол наклона", "от 20° до 25°", 1.0, "ПЗР"),
            CorrectionCoefficient("Угол наклона", "от 25,1° до 45°", 1.15, "ПЗР"),
            CorrectionCoefficient("Угол наклона", "до 20°", 1.0, "Работа_на_скважине"),
            CorrectionCoefficient("Угол наклона", "от 20° до 25°", 1.0, "Работа_на_скважине"),
            CorrectionCoefficient("Угол наклона", "от 25,1° до 45°", 1.15, "Работа_на_скважине"),
            CorrectionCoefficient("Угол наклона", "до 20°", 1.0, "Спуск_подъем"),
            CorrectionCoefficient("Угол наклона", "от 20° до 25°", 1.0, "Спуск_подъем"),
            CorrectionCoefficient("Угол наклона", "от 25,1° до 45°", 1.15, "Спуск_подъем"),
        ])
        
        return coefficients
    
    def get_temperature_coefficient(self, temperature: float, work_type: str = "Работа_на_скважине") -> float:
        """Получить коэффициент для температуры"""
        temp = float(temperature)
        
        if -5 <= temp <= 35:
            return 1.0
        elif (-20 <= temp < -5) or temp > 35:
            return 1.17
        elif temp < -20:
            return 1.34
        else:
            return 1.0
    
    def get_angle_coefficient(self, angle: float, work_type: str = "Работа_на_скважине") -> float:
        """Получить коэффициент для угла наклона.

        В таблице поправочных коэффициентов (Прил. №6 к ЕНВиР-99-Л-3С)
        последняя строка — "от 25,1 град. до 45 град.": 1.15, без верхней
        границы диапазона в реальных актах. Проверено на актах с углом
        48,08°, 56,78° и 90,91° — во всех коэффициент в акте соответствует
        1.15, а не откату к 1.0. Возможно, где-то дальше есть ещё более
        высокий разряд — данных для этого пока не было.
        """
        ang = float(angle)

        if ang <= 25:
            return 1.0
        return 1.15
    
    def get_integral_coefficient(self, temperature: float, angle: float) -> float:
        """
        Рассчитать интегральный коэффициент по формуле:
        K_int = K_temp + K_angle - 1
        """
        k_temp = self.get_temperature_coefficient(temperature)
        k_angle = self.get_angle_coefficient(angle)
        
        # Основная формула расчета интегрального коэффициента
        k_integral = k_temp + k_angle - 1
        
        return round(k_integral, 2)


class IntegralCoefficientCalculator:
    """Класс для расчета интегрального коэффициента"""
    
    def __init__(self):
        self.coefficient_table = CoefficientTable()
    
    def parse_well_data(self, pdf_path: str) -> Dict:
        """Парсит данные из PDF файла"""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                text = pdf.pages[0].extract_text() if pdf.pages else ""
                
                # Парсим температуру
                temperature = self._parse_temperature(text)
                
                # Парсим угол наклона
                angle = self._parse_angle(text)
                
                # Парсим интегральный коэффициент из таблицы
                integral_from_table = self._parse_integral_coefficient_from_table(text)
                
                return {
                    'filename': os.path.basename(pdf_path),
                    'temperature': temperature,
                    'angle': angle,
                    'integral_from_table': integral_from_table,
                }
                
        except Exception as e:
            print(f"Ошибка при парсинге {pdf_path}: {str(e)}")
            return {
                'filename': os.path.basename(pdf_path),
                'temperature': None,
                'angle': None,
                'integral_from_table': None,
            }
    
    def _parse_temperature(self, text: str) -> Optional[float]:
        """Парсит температуру из текста"""
        lines = text.split('\n')
        for line in lines:
            if 'Температура воздуха' in line:
                line_processed = re.sub(r'(?<=\d)\.(?=[\d,])', '', line)
                match = re.search(r'Температура воздуха[^\d\-]*(-?\d+)[,\.]?(\d*)', line_processed)
                if match:
                    temp_str = match.group(1)
                    if match.group(2):
                        temp_str += '.' + match.group(2)
                    try:
                        return float(temp_str.replace(',', '.'))
                    except Exception:
                        return None
        return None
    
    def _parse_angle(self, text: str) -> Optional[float]:
        """Парсит угол наклона из текста"""
        lines = text.split('\n')
        for line in lines:
            if 'Угол наклона' in line:
                line_clean = line.replace(' ', '')
                
                # Для формата "2.4,89"
                match = re.search(r'Уголнаклона[^\d]*(\d+)\.(\d+),(\d+)', line_clean)
                if match:
                    angle_str = f"{match.group(1)}{match.group(2)}.{match.group(3)}"
                    try:
                        return float(angle_str)
                    except Exception:
                        return None
                
                # Для формата "36,5"
                match = re.search(r'Уголнаклона[^\d]*(\d+),(\d+)', line_clean)
                if match:
                    angle_str = f"{match.group(1)}.{match.group(2)}"
                    try:
                        return float(angle_str)
                    except Exception:
                        return None
                
                # Общий случай
                match = re.search(r'Уголнаклона[^\d]*(\d+)', line_clean)
                if match:
                    try:
                        return float(match.group(1))
                    except Exception:
                        return None
        
        return None
    
    def _parse_integral_coefficient_from_table(self, text: str) -> Optional[float]:
        """Извлекает интегральный коэффициент из таблицы расценок в PDF."""
        lines = text.split('\n')
        is_vatieganskoe = 'ватьеган' in text.lower()
        is_povhovskoe = 'повхов' in text.lower()

        if is_vatieganskoe:
            target_coeff = 1.32
            target_patterns = [r'1[,\.]32', r'1\.32', r'1,32']
        elif is_povhovskoe:
            target_coeff = 1.00
            target_patterns = [r'1[,\.]00', r'1\.00', r'1,00', r'1\.0', r'1,0']
        else:
            return None

        # Шаг 1: ищем заголовок колонки «интегральный коэффициент», затем значение ниже
        table_start = -1
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if ('интег' in line_lower and 'коэф' in line_lower) or \
               ('инт' in line_lower and 'коэф' in line_lower):
                table_start = i
                break

        if table_start != -1:
            for i in range(table_start + 1, min(table_start + 15, len(lines))):
                line = lines[i].strip()
                if not line or 'наименование' in line.lower():
                    continue
                for pattern in target_patterns:
                    if re.search(pattern, line) and re.search(r'\d+,\d+', line):
                        return target_coeff

        # Шаг 2: ищем паттерн прямо в строках таблицы (без заголовка)
        for line in lines:
            line_clean = line.strip()
            if (len(line_clean) > 30
                    and re.search(r'\d+,\d+.*\d+,\d+', line_clean)
                    and not any(w in line_clean.lower()
                                for w in ('наименование', 'стоимость', 'итог', 'всего'))):
                for pattern in target_patterns:
                    m = re.search(pattern, line_clean)
                    if m:
                        try:
                            coeff = float(m.group().replace(',', '.'))
                            if (is_vatieganskoe and coeff == 1.32) or \
                               (is_povhovskoe and abs(coeff - 1.00) < 0.01):
                                return coeff
                        except Exception:
                            continue

        # Шаг 3: статистический метод — самое частое число в диапазоне 1.0–1.5
        all_numbers: list[float] = []
        for pat in (r'\b(\d)[,\.](\d{2})\b', r'\b(\d)[,\.](\d)\b'):
            for int_part, dec_part in re.findall(pat, text):
                try:
                    num = float(f"{int_part}.{dec_part}")
                    if 1.0 <= num <= 1.5:
                        all_numbers.append(num)
                except Exception:
                    continue

        if all_numbers:
            counter = Counter(all_numbers)
            if is_vatieganskoe:
                if 1.32 in counter:
                    return 1.32
                non_one = [c for c in counter if abs(c - 1.00) > 0.01]
                if non_one:
                    return max(non_one, key=lambda x: counter[x])
            if is_povhovskoe:
                for coeff in counter:
                    if abs(coeff - 1.00) < 0.01:
                        return coeff
            return counter.most_common(1)[0][0]

        # Коэффициент не найден в документе — возвращаем None,
        # чтобы проверка показала ❌ вместо ложного ✅
        return None
    
    def calculate_and_compare(self, pdf_path: str) -> Dict:
        """Рассчитывает интегральный коэффициент и сравнивает с табличным значением."""
        well_data = self.parse_well_data(pdf_path)

        if well_data['temperature'] is None or well_data['angle'] is None:
            return {
                'filename': well_data['filename'],
                'temperature': well_data['temperature'],
                'angle': well_data['angle'],
                'calculated': None,
                'from_table': well_data['integral_from_table'],
                'match': False,
                'error': 'Не удалось распарсить температуру или угол'
            }

        calculated_coeff = self.coefficient_table.get_integral_coefficient(
            temperature=well_data['temperature'],
            angle=well_data['angle']
        )
        table_coeff = well_data['integral_from_table']
        match = table_coeff is not None and abs(calculated_coeff - table_coeff) < 0.01

        return {
            'filename': well_data['filename'],
            'temperature': well_data['temperature'],
            'angle': well_data['angle'],
            'calculated': calculated_coeff,
            'from_table': table_coeff,
            'match': match,
            'error': None
        }


class IntegralProcessor:
    """Обработчик для расчета интегральных коэффициентов.

    Построчная сверка (по факт. строкам расценок в акте, а не по одному
    зашитому значению на весь документ) — см. FinalUnifiedParser в
    main_parser.py, метод _check_integral_rows.
    """

    def process_all_pdfs(self) -> List["WellData"]:
        """Обрабатывает все PDF файлы"""
        input_dir = get_input_dir()
        pdf_files = list(input_dir.glob("*.pdf"))
        if not pdf_files:
            print(f"❌ PDF файлы не найдены в: {input_dir}")
            return []
        return self.process_pdfs(pdf_files)

    def process_pdfs(self, pdf_paths: List[Path]) -> List["WellData"]:
        """Обрабатывает указанные PDF файлы"""
        from src.extractors.main_parser import FinalUnifiedParser

        parser = FinalUnifiedParser()
        return [parser.parse_all(str(pdf_file)) for pdf_file in pdf_paths]

    def print_results(self, results: List["WellData"]):
        """Выводит результаты расчета"""
        for well_data in results:
            print(f"\n{well_data.filename}")
            _print_integral_row_report(well_data)


def _print_integral_row_report(well_data) -> None:
    if not well_data.integral_row_status:
        print("🧮 Интегральный коэффициент: данных нет")
        return
    icon = "✅" if well_data.integral_row_status == "ok" else "❌"
    print(f"🧮 Интегральный коэффициент: {icon}")
    for line in well_data.integral_row_details:
        print(f"  {line}")


def run_report(pdf_paths, wells_data) -> None:
    """Печатает уже посчитанный (в main_parser.parse_all) построчный
    интегральный коэффициент — не открывает и не парсит PDF заново."""
    ensure_runtime_layout(copy_reference=True)
    by_name = {getattr(wd, "filename", None): wd for wd in wells_data}
    for pdf_path in pdf_paths:
        pdf_path = Path(pdf_path)
        well_data = by_name.get(pdf_path.name)
        print(f"\n{pdf_path.name}:")
        if well_data is None or not well_data.integral_row_status:
            print("  Интегральный коэффициент: данных нет")
            continue
        status = well_data.integral_row_status
        icon = "✅" if status == "ok" else "❌"
        print(f"  Интегральный коэффициент: {icon}")
        for line in well_data.integral_row_details:
            print(f"    {line}")


def main(args: List[str] | None = None):
    """Главная функция - расчет интегральных коэффициентов"""
    ensure_runtime_layout(copy_reference=True)
    processor = IntegralProcessor()

    input_dir = get_input_dir()

    cli_args = args if args is not None else sys.argv[1:]
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
        results = processor.process_pdfs(pdf_paths)
    else:
        # 1. Обрабатываем все PDF файлы
        results = processor.process_all_pdfs()

    if not results:
        print("❌ Результаты не найдены")
        return

    # 2. Выводим результаты
    processor.print_results(results)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Программа прервана пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
