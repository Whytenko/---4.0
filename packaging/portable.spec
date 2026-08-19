# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

project_root = Path.cwd()
app_name = "AKTNaryadVerifier"

datas = [
    (str(project_root / "data" / "reference"), "data/reference"),
    (str(project_root / "MLdata(Лист1)-2.csv"), "."),
]

tesseract_dir = project_root / "tesseract"
if tesseract_dir.exists():
    datas.append((str(tesseract_dir), "tesseract"))

for asset_name in (
    "basket.svg",
    "check_file.svg",
    "download_file.svg",
    "folder.svg",
    "integral.svg",
    "km_parser.svg",
    "logo-lu.svg",
    "lukoil-desk.png",
    "lukoil-desk.ico",
    "lukoil35.ico",
    "lukoil35.webp",
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
    excludes=[],
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
    icon=str(project_root / "lukoil-desk.ico")
    if (project_root / "lukoil-desk.ico").exists()
    else (str(project_root / "lukoil35.ico") if (project_root / "lukoil35.ico").exists() else None),
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
