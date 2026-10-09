"""
Титульный лист акт-наряда, не уместившийся на одной странице.

Обычно вся таблица расценок вместе с итогами ("И т о г о по Акт-наряду",
"Всего с учетом коэффициента", "Всего к оплате") помещается на титульном
листе. В длинных актах хвост таблицы и/или итоговые строки уходят на
следующий лист — тогда парсер, читающий только титульный лист, не находил
ни стоимость, ни коэффициент по договору, терял часть строк расценок и
принимал лист-продолжение за скан "АКТ-ЗАКАЗ".

Отдельный модуль (а не метод FinalUnifiedParser), потому что нужен и
main_parser, и km_parser, а km_parser импортируется из main_parser.
"""
from __future__ import annotations

from typing import List

# Последняя строка итогового блока — признак того, что таблица закончилась.
ACT_END_MARKER = "всего к оплате"

# Начало другого документа внутри того же PDF — дальше продолжение не ищем.
_FOREIGN_PAGE_MARKERS = (
    "акт - заказ",
    "акт-заказ",
    "приложение №1",
    "приложение n1",
    "выполнение комплекса гирс по договору",
)

# Таблица расценок не бывает длиннее пары листов; ограничение — страховка
# от склейки титула с посторонними страницами.
_MAX_CONTINUATION_PAGES = 3


def _page_text(page) -> str:
    try:
        return page.extract_text() or ""
    except Exception:
        return ""


def continuation_page_indices(pdf, header_idx: int = 0) -> List[int]:
    """Индексы страниц, на которые перешёл титульный лист акт-наряда.
    Пустой список — обычный акт (итоги на самом титульном листе) либо
    конец таблицы так и не найден (тогда ничего не приклеиваем)."""
    pages = getattr(pdf, "pages", None) or []
    if header_idx < 0 or header_idx >= len(pages):
        return []
    if ACT_END_MARKER in _page_text(pages[header_idx]).lower():
        return []

    found: List[int] = []
    last = min(len(pages), header_idx + 1 + _MAX_CONTINUATION_PAGES)
    for idx in range(header_idx + 1, last):
        norm = _page_text(pages[idx]).lower()
        if not norm.strip():
            break
        if any(marker in norm for marker in _FOREIGN_PAGE_MARKERS):
            break
        found.append(idx)
        if ACT_END_MARKER in norm:
            return found
    return []


def act_text(pdf, header_idx: int = 0) -> str:
    """Текст титульного листа вместе с листами-продолжениями."""
    pages = getattr(pdf, "pages", None) or []
    if header_idx < 0 or header_idx >= len(pages):
        return ""
    parts = [_page_text(pages[header_idx])]
    parts.extend(_page_text(pages[idx]) for idx in continuation_page_indices(pdf, header_idx))
    return "\n".join(part for part in parts if part)
