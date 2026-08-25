import re
import sys
from pathlib import Path
from types import SimpleNamespace
import pdfplumber
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.app_paths import ensure_runtime_layout, get_input_dir, get_reference_dir

def _parse_float(value):
    if value is None:
        return None
    try:
        return float(str(value).replace(',', '.'))
    except Exception:
        return None

def parse_field(text: str) -> str:
    match = re.search(r'Месторождение[^А-Я]*([А-Я][а-я]+ское|[А-Я][а-я]+ное)', text)
    return match.group(1) if match else ""

def parse_bush(text: str) -> str:
    # Формат "Номер скважины / куст ... 622 / 27" проверяем ПЕРВЫМ и
    # регистро-независимо: номер скважины может иметь буквенный суффикс
    # ("1996Л"), поэтому между цифрами и "/" не обязательно сразу пробел/слэш.
    # Куст тоже может иметь буквенный суффикс ("115Б") — это отдельный
    # "Вид куста" в справочнике по километражу (см. split_bush), и без
    # него сверка может взять не ту строку справочника (разные расстояния
    # для "115" и "115 Б").
    match = re.search(r'скважины\s*/\s*куст[^0-9]*\d+[^/]*/\s*([0-9]+[А-Яа-я]?)', text, re.IGNORECASE)
    if match:
        return match.group(1)
    # Отдельная строка вида "Куст: 29" (без привязки к номеру скважины) —
    # регистрозависимо, иначе ложно совпадает с "куст" внутри "Номер
    # скважины / куст......." и захватывает номер скважины вместо куста.
    match = re.search(r'Куст[^0-9]*([0-9]+[А-Яа-я]?)', text)
    return match.group(1) if match else ""


def split_bush(bush: str) -> tuple:
    """Разбивает куст на числовую часть и буквенный 'Вид куста'
    ('115Б' -> ('115', 'Б'), '446' -> ('446', ''))."""
    match = re.match(r'([0-9]+)([А-Яа-я]?)', bush or "")
    if not match:
        return bush or "", ""
    return match.group(1), match.group(2)

def _nth_number(line: str, n: int):
    nums = re.findall(r'\d+[.,]?\d*', line)
    if len(nums) >= n:
        return _parse_float(nums[n - 1])
    return None

def parse_relocation_values(text: str):
    v1 = None
    v3 = None
    voff = None
    for line in text.split('\n'):
        if 'Переезд перфораторной партии' not in line and 'Переезд комп.партии' not in line and 'Переезд комп. партии' not in line:
            continue
        if re.search(r'переезд .*1\s*гр', line, re.IGNORECASE) and v1 is None:
            m = re.search(r'0,0\s+0,0\s+([0-9]+[.,]?[0-9]*)', line)
            v1 = _parse_float(m.group(1)) if m else _nth_number(line, 5)
        if re.search(r'переезд .*3\s*гр', line, re.IGNORECASE) and v3 is None:
            m = re.search(r'0,0\s+0,0\s+([0-9]+[.,]?[0-9]*)', line)
            v3 = _parse_float(m.group(1)) if m else _nth_number(line, 5)
        if re.search(r'переезд .*бездорож', line, re.IGNORECASE) and voff is None:
            m = re.search(r'0,0\s+0,0\s+([0-9]+[.,]?[0-9]*)', line)
            voff = _parse_float(m.group(1)) if m else _nth_number(line, 5)
    # Fallback: search near "1 гр", "3 гр" и "бездорожье"
    if v1 is None:
        match1 = re.search(r'Переезд перфораторной партии.*?1\s*гр[^0-9]*([0-9]+[.,]?[0-9]*)', text, re.IGNORECASE | re.DOTALL)
        v1 = _parse_float(match1.group(1)) if match1 else None
    if v3 is None:
        match3 = re.search(r'Переезд перфораторной партии.*?3\s*гр[^0-9]*([0-9]+[.,]?[0-9]*)', text, re.IGNORECASE | re.DOTALL)
        v3 = _parse_float(match3.group(1)) if match3 else None
    if voff is None:
        match_off = re.search(r'Переезд перфораторной партии.*?бездорож[^0-9]*([0-9]+[.,]?[0-9]*)', text, re.IGNORECASE | re.DOTALL)
        voff = _parse_float(match_off.group(1)) if match_off else None
    return v1, v3, voff

def get_report_values(field: str, bush: str):
    excel_path = get_reference_dir() / "17. Отчет по километражу.xlsx"
    if not excel_path.exists():
        return None, None, None
    bush_number, bush_type = split_bush(bush)
    df = pd.read_excel(excel_path, sheet_name="Sheet1", header=None)
    fallback_row = None
    for i in range(2, df.shape[0]):
        f = str(df.iloc[i, 0]).strip()
        b = str(df.iloc[i, 1]).strip()
        if not f or f == "nan":
            continue
        if field.lower() not in f.lower() or b != bush_number:
            continue
        # "Вид куста" (столбец C, 0-based индекс 2) различает несколько
        # маршрутов для ОДНОГО номера куста ("115" и "115 Б" — разные
        # расстояния) — без учёта вида сверка может взять не ту строку.
        row_type = str(df.iloc[i, 2] or "").strip()
        if row_type.lower() == (bush_type or "").lower():
            row = df.iloc[i]
        elif fallback_row is None:
            fallback_row = df.iloc[i]
            continue
        else:
            continue
        # столбцы (1-based): D=4 "Проезд, 1 категории", E=5 "Проезд, 3
        # категории", F=6 "Проезд бездорожье" (0-based: 3, 4, 5)
        v1 = _parse_float(row.iloc[3])
        v3 = _parse_float(row.iloc[4])
        voff = _parse_float(row.iloc[5])
        return v1, v3, voff
    if fallback_row is not None:
        return (
            _parse_float(fallback_row.iloc[3]),
            _parse_float(fallback_row.iloc[4]),
            _parse_float(fallback_row.iloc[5]),
        )
    return None, None, None

def _ocr_relocation_area(page) -> str:
    """OCR той же области скана «АКТ-ЗАКАЗ», где main_parser читает даты
    («Начало/Окончание работы...») — чуть ниже в той же колонке стоит
    «Приезд на базу (переезд на другой объект)», которую здесь и ищем."""
    try:
        import pytesseract
        from PIL import ImageOps
    except Exception:
        return ""
    try:
        from src.extractors.main_parser import FinalUnifiedParser
    except Exception:
        return ""
    if not FinalUnifiedParser()._configure_tesseract(pytesseract):
        return ""
    h, w = page.height, page.width
    crop = page.crop((w * 0.60, h * 0.30, w * 0.98, h * 0.65))
    image = crop.to_image(resolution=300).original
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    try:
        return pytesseract.image_to_string(gray, lang="rus+eng", config="--psm 6", timeout=10)
    except Exception:
        return ""


def _has_relocation_note(pdf) -> bool:
    """На 2 листе иногда стоит пометка 'Приезд на базу (переезд на другой
    объект)' — по инструкции это законная причина, почему объём переезда в
    акте меньше отчётного (часть маршрута выполнена в рамках другого акта).
    Эта страница обычно отсканирована как картинка (extract_text пуст), а
    физическая позиция может сдвигаться — поэтому пробуем несколько первых
    страниц и, если текста нет, распознаём его через OCR. Также встречается
    формулировка "далее задача №..." вместо явного "переезд на другой
    объект" — партия едет прямо на следующую задачу, не возвращаясь на базу."""
    for idx in range(min(len(pdf.pages), 4)):
        try:
            text = pdf.pages[idx].extract_text() or ""
        except Exception:
            text = ""
        if not text:
            text = _ocr_relocation_area(pdf.pages[idx])
        norm = text.lower()
        # Короткий, устойчивый к OCR-ошибкам фрагмент: слово "переезд" в
        # начале фразы искажается чаще всего ("езл на другой объект)"
        # вместо "переезд на другой объект)" — по факту OCR реальных
        # сканов), а "на другой объект" распознаётся стабильно.
        if "на другой объект" in norm or "далее задача" in norm:
            return True
    return False


def compute_km_report(pdf_path: Path) -> dict:
    """Считает сверку километража без печати (используется и консольным
    отчётом, и пакетным Excel-отчётом)."""
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text() if pdf.pages else ""
        relocation_note = _has_relocation_note(pdf)
    field = parse_field(text)
    bush = parse_bush(text)
    v1, v3, voff = parse_relocation_values(text)
    # "Бездорожье" и "3 гр.дорог" в реальных актах — взаимоисключающие
    # ярлыки ОДНОЙ и той же категории проезда, а не три независимые
    # категории: ни в одном из 86 реальных актов выборки не встретилось
    # обеих строк одновременно (только "1 гр"+"3 гр" ИЛИ "1 гр"+
    # "бездорожье"). Когда акт использует именно "бездорожье" (а "3
    # гр.дорог" при этом не найдено), число там численно совпадает с
    # эталонной "3 категории" (напр. акт 12432: бездорожье=11.80,
    # эталон "3 кат." туда-обратно=11.8) — контрагент так называет ту же
    # графу. Раньше это число сравнивалось с эталонной "бездорожье"
    # (часто 0 или другое значение) — отсюда ложные "несхождения".
    if v3 is None and voff is not None:
        v3, voff = voff, None
    field, bush, v1, v3, ml_used = _apply_ml_overrides(pdf_path, field, bush, v1, v3)
    r1_one_way, r3_one_way, roff_one_way = (
        get_report_values(field, bush) if field and bush else (None, None, None)
    )

    # Справочник хранит расстояние в одну сторону; в акте обычно
    # фиксируется туда+обратно — но не всегда: на реальных актах
    # встречаются случаи (напр. 000083, 12435), где оба значения акта
    # ТОЧНО совпадают с "одну сторону" эталона, а не с туда-обратно.
    # Соглашение варьируется от акта к акту, а не общее для всех — и
    # надёжного признака "какой это акт" нет, поэтому сравниваем с ОБОИМИ
    # вариантами и принимаем совпадение с любым из них.
    def _double(value):
        return value * 2 if value is not None else None

    r1 = _double(r1_one_way)
    r3 = _double(r3_one_way)
    roff = _double(roff_one_way)

    def _compare(actual, expected, expected_one_way=None):
        if actual is None or expected is None:
            return None
        if abs(actual - expected) <= 0.1:
            return "ok"
        if expected_one_way is not None and abs(actual - expected_one_way) <= 0.1:
            return "ok"
        # В акте объём переезда может быть меньше отчётного, если часть
        # маршрута ушла на переезд партии на другой объект (см. 2 лист).
        if relocation_note and actual < expected:
            return "conditional_ok"
        return "bad"

    result1 = _compare(v1, r1, r1_one_way)
    result3 = _compare(v3, r3, r3_one_way)
    result_off = _compare(voff, roff, roff_one_way)
    results = (result1, result3, result_off)

    if all(r is None for r in results):
        overall = "neutral"
    elif any(r == "bad" for r in results):
        overall = "bad"
    elif any(r == "conditional_ok" for r in results):
        overall = "conditional_ok"
    else:
        overall = "ok"

    return {
        "status": overall,
        "bush": bush,
        "v1": v1,
        "v3": v3,
        "voff": voff,
        "r1": r1,
        "r3": r3,
        "roff": roff,
        "result1": result1,
        "result3": result3,
        "result_off": result_off,
        "relocation_note": relocation_note,
    }


def process_pdf(pdf_path: Path):
    result = compute_km_report(pdf_path)

    print(f"\nОтчет по километражу: {pdf_path.name}")
    print(f"Куст: {result['bush'] if result['bush'] else 'не найден'}")
    print(f"Переезд 1 гр.: {result['v1'] if result['v1'] is not None else 'не найдено'}")
    print(f"Переезд 3 гр.: {result['v3'] if result['v3'] is not None else 'не найдено'}")
    print(f"Переезд бездорожье: {result['voff'] if result['voff'] is not None else 'не найдено'}")
    print(f"По отчету 1 гр.: {result['r1'] if result['r1'] is not None else 'не найдено'}")
    print(f"По отчету 3 гр.: {result['r3'] if result['r3'] is not None else 'не найдено'}")
    print(f"По отчету бездорожье: {result['roff'] if result['roff'] is not None else 'не найдено'}")

    def _format_result(label: str, result_status) -> None:
        if result_status is None:
            return
        if result_status == "ok":
            print(f"Результат {label}: ✅ СООТВЕТСТВУЕТ")
        elif result_status == "conditional_ok":
            print(f"Результат {label}: ✅ СООТВЕТСТВУЕТ (переезд на другой объект, см. акт-заказ)")
        else:
            print(f"Результат {label}: ❌ НЕ СООТВЕТСТВУЕТ")

    _format_result("1 гр.", result["result1"])
    _format_result("3 гр.", result["result3"])
    _format_result("бездорожье", result["result_off"])

def _apply_ml_overrides(pdf_path: Path, field: str, bush: str, v1, v3):
    try:
        from src.extractors.ml_assist import MLAssist, _parse_ru_int, _parse_ru_float
    except Exception:
        try:
            from ml_assist import MLAssist, _parse_ru_int, _parse_ru_float
        except Exception:
            return field, bush, v1, v3, False

    assist = MLAssist.load()
    if assist is None:
        return field, bush, v1, v3, False

    # Только точное совпадение по имени файла нам и нужно — используем
    # match_exact() напрямую, чтобы не запускать на каждый файл полный
    # KNN-перебор по всему ML-справочнику ради результата, который всё
    # равно отбрасывается, если это не exact-file.
    match = assist.match_exact(SimpleNamespace(filename=pdf_path.name))
    if match is None:
        return field, bush, v1, v3, False

    row = match.row
    changed = False

    if "field" in row and not pd.isna(row["field"]):
        value = str(row["field"]).strip()
        if value:
            field = value
            changed = True
    if "well_bush" in row and not pd.isna(row["well_bush"]):
        parsed = _parse_ru_int(row["well_bush"])
        if parsed is not None:
            bush = str(parsed)
            changed = True
    if "km_reloc_1gr" in row and not pd.isna(row["km_reloc_1gr"]):
        parsed = _parse_ru_float(row["km_reloc_1gr"])
        if parsed is not None:
            v1 = parsed
            changed = True
    if "km_reloc_3gr" in row and not pd.isna(row["km_reloc_3gr"]):
        parsed = _parse_ru_float(row["km_reloc_3gr"])
        if parsed is not None:
            v3 = parsed
            changed = True

    return field, bush, v1, v3, changed

def main(args=None):
    ensure_runtime_layout(copy_reference=True)
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
    else:
        pdf_paths = list(input_dir.glob("*.pdf"))

    if not pdf_paths:
        print("❌ Файлы не найдены")
        return

    for pdf in pdf_paths:
        process_pdf(pdf)

if __name__ == "__main__":
    main()
