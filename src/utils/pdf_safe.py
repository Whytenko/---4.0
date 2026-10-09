"""
Защита от "битых" страниц PDF.

В реальных актах встречаются склеенные PDF, где у отдельного листа
(обычно не относящегося к проверке — например "Оценка работы
геофизической партии") повреждены ссылки на объекты шрифта. pdfminer на
таком листе падает (AttributeError: 'dict' object has no attribute
'decode'), pdfplumber заворачивает это в PdfminerException, и из-за одного
ненужного листа весь акт уходил в "ошибка" по всем полям.

install() делает такой лист "пустым" (без текста и таблиц) вместо
исключения: остальные страницы акта разбираются как обычно, а растровые
операции (to_image → OCR) идут через pypdfium2 и от этого не зависят.
"""
from __future__ import annotations

_installed = False


def install() -> None:
    global _installed
    if _installed:
        return
    try:
        from pdfplumber.page import Page
        from pdfplumber.utils.exceptions import PdfminerException
    except Exception:
        return

    original_parse_objects = Page.parse_objects

    def _safe_parse_objects(self):
        try:
            return original_parse_objects(self)
        except PdfminerException:
            return {}

    Page.parse_objects = _safe_parse_objects
    _installed = True


install()
