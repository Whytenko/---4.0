# config/regex_patterns.py

"""
Регулярные выражения для извлечения данных с первой страницы акт-наряда (PDF).
"""
import re

PATTERNS = {
    # Для левого столбца
    'field': re.compile(r'Месторождение[\.\s]*([^\n\r]+?)(?=\s{2,}|$)'),
    'well': re.compile(r'Номер скважины\s*/\s*куст[\.\s]*(\d+)\s*/\s*(\d+)'),
    'angle': re.compile(r'Угол наклона скв\.градус[\.\s]*([\d,]+)'),
    'air_temp': re.compile(r'Температура воздуха, градус[\.\s]*([-\d,]+)'),
    'descent_method': re.compile(r'Спуск/подъем[\.\s]*([^\n\r]+?)(?=\s{2,}|$)'),
    
    # Для правого столбца
    'order_number': re.compile(r'Заказ №[\.\s]*(\d+)'),
    'start_date': re.compile(r'Начало работ на скв[\.\s]*(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})'),
    'end_date': re.compile(r'Окончание работ на скв[\.\s]*(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})'),
    
    # Для таблицы
    'descent_in_hole': re.compile(r'С/п скв\.приб\.'),
    
    # Общие
    'akt_number_from_text': re.compile(r'АКТ - HАРЯД №\s*(\d+)'),
    'cable_mileage': re.compile(r'Общий пробег кабеля\s*([\d,]+)'),
    'vm_cost_total': re.compile(r'Стоимость ВМ \(тип ВМ\) в т\.ч\.:\s*[\s\S]*?([\d\s,]+)\n'),
}

def find_first(pattern, text, group=1):
    """Ищет первое совпадение в тексте."""
    if not text or not pattern:
        return None
    match = pattern.search(text)
    if match:
        return match.group(group).strip()
    return None