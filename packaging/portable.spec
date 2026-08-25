# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

project_root = Path.cwd()
app_name = "AKTNaryadVerifier"

datas = [
    (str(project_root / "data" / "reference"), "data/reference"),
    (str(project_root / "MLdata(Лист1)-2.csv"), "."),
]

# webview хранит JS-мост (js/api.js и др.) и нативные WebView2 DLL
# (WebView2Loader.dll, WebBrowserInterop.x64.dll и т.д.) как файлы данных
# пакета, а не Python-модули — collect_submodules их не подхватывает.
# Без них статический HTML/CSS рисуется нормально, а любой вызов
# pywebview.api.*() из JS зависает навсегда: мост никогда не подключается.
datas += collect_data_files("webview")

tesseract_dir = project_root / "tesseract"
if tesseract_dir.exists():
    datas.append((str(tesseract_dir), "tesseract"))

for asset_name in (
    "basket.svg",
    "batch.svg",
    "check_file.svg",
    "download_file.svg",
    "folder.svg",
    "integral.svg",
    "km_parser.svg",
    "logo-lu.svg",
    "lukoil-desk.png",
    "lukoil-app.ico",
    "lukoil-desk.ico",
    "lukoil35.ico",
    "lukoil35.webp",
    "lukoil35-anniversary.png",
    "main_parser.svg",
    "skvazhina.svg",
    "table_parser.svg",
):
    asset_path = project_root / asset_name
    if asset_path.exists():
        datas.append((str(asset_path), "."))

hiddenimports = sorted(
    set(
        collect_submodules("src.extractors")
        + collect_submodules("webview")
        + [
            "integral",
            "src.utils.app_paths",
            "pdfplumber",
            "pytesseract",
            "PIL",
            "pandas",
            "openpyxl",
            "sklearn",
        ]
    )
)

block_cipher = None

a = Analysis(
    [str(project_root / "interface.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # pyarrow (arrow.dll) — крашит процесс access violation'ом на связке
    # Python 3.13, если случайно попадёт в сборку как транзитивная
    # зависимость. requirements.txt уже держит pandas<3.0 (не требует
    # pyarrow), это исключение — вторая линия защиты на случай, если
    # pyarrow всё равно окажется установлен в окружении сборки.
    excludes=["pyarrow"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=next(
        (str(project_root / name) for name in ("lukoil-app.ico", "lukoil35.ico", "lukoil-desk.ico")
         if (project_root / name).exists()),
        None,
    ),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_name,
)
