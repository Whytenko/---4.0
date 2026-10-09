#!/usr/bin/env python3
"""
AKT-NARYAD VERIFIER - PyWebView Interface
HTML/CSS без сервера
"""

import webview
import sys
from pathlib import Path
import subprocess
import os
import shutil
import ctypes
import time
import io
import json
import importlib
import traceback
from contextlib import redirect_stdout, redirect_stderr
from urllib.parse import quote

from src.utils.app_paths import ensure_runtime_layout, get_input_dir, get_reference_dir, get_runtime_root
from src.utils.healthcheck import format_self_check_report, run_self_check
from src.utils.smoke_test import format_smoke_report, run_smoke_test


def _configure_console_streams():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


class API:
    def __init__(self):
        self.project_root = Path(__file__).parent
        ensure_runtime_layout(copy_reference=True)
        self.runtime_root = get_runtime_root()
        self.input_folder = get_input_dir()
        self.window = None
        try:
            self.self_check = run_self_check(write_logs=True)
        except Exception:
            self.self_check = None

    def run_main_parser(self, file_name=None):
        return self.run_parser("main_parser.py", file_name)
    
    def run_table_parser(self, file_name=None):
        return self.run_parser("table_parser.py", file_name)
    
    def run_integral_calculator(self, file_name=None):
        return self.run_parser("integral.py", file_name)

    def _run_module_main(self, module_name, args):
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        try:
            module = importlib.import_module(module_name)
        except Exception:
            traceback.print_exc(file=stderr_buffer)
            return "", stderr_buffer.getvalue()

        main_fn = getattr(module, "main", None)
        if not callable(main_fn):
            stderr_buffer.write(f"Модуль {module_name} не содержит функцию main()\n")
            return "", stderr_buffer.getvalue()

        with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
            try:
                main_fn(args)
            except TypeError:
                old_argv = sys.argv[:]
                try:
                    sys.argv = [module_name] + list(args)
                    main_fn()
                finally:
                    sys.argv = old_argv
            except Exception:
                traceback.print_exc()

        return stdout_buffer.getvalue(), stderr_buffer.getvalue()

    
    def run_parser(self, script_name, file_name=None):
        module_map = {
            "main_parser.py": "src.extractors.main_parser",
            "table_parser.py": "src.extractors.table_parser",
            "km_parser.py": "src.extractors.km_parser",
            "integral.py": "integral",
        }
        
        try:
            parser_args = []
            if file_name:
                selected_path = self.input_folder / file_name
                if not selected_path.exists():
                    return f"❌ Файл не найден: {selected_path}"
                parser_args.append(str(selected_path))

            stdout = ""
            stderr = ""
            module_name = module_map.get(script_name)

            if module_name:
                stdout, stderr = self._run_module_main(module_name, parser_args)
            else:
                possible_paths = [
                    self.project_root / "src" / "extractors" / script_name,
                    self.project_root / script_name,
                ]
                script_path = None
                for path in possible_paths:
                    if path.exists():
                        script_path = path
                        break
                if not script_path:
                    return f"❌ Файл не найден: {script_name}\n\nИскали в:\n• {possible_paths[0]}\n• {possible_paths[1]}"

                args = [sys.executable, str(script_path)] + parser_args
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                result = subprocess.run(
                    args,
                    cwd=self.project_root,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
                stdout = result.stdout
                stderr = result.stderr
            
            if script_name == "main_parser.py":
                output = "🚀 АНАЛИЗ ФАЙЛА\n"
            else:
                output = f"🚀 ЗАПУСК {script_name.upper()}\n"
            if file_name:
                output += f"Файл: {file_name}\n"
            output += f"Папка данных: {self.runtime_root}\n"
            if self.self_check:
                output += (
                    f"Самопроверка: {str(self.self_check.get('status', 'unknown')).upper()} "
                    f"(ошибок: {self.self_check.get('errors', 0)}, "
                    f"предупреждений: {self.self_check.get('warnings', 0)})\n"
                )
            output += "=" * 50 + "\n\n"
            output += stdout
            
            if stderr:
                output += "\n" + "─" * 50 + "\n"
                output += "⚠️  ОШИБКИ:\n"
                output += "─" * 50 + "\n"
                output += stderr
            
            output += "\n" + "=" * 50 + "\n"
            output += f"✅ {script_name} ЗАВЕРШЕН\n"
            
            return output
            
        except Exception as e:
            return f"❌ ОШИБКА: {str(e)}"
    
    def open_folder(self):
        try:
            if sys.platform == "win32":
                os.startfile(self.input_folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.input_folder])
            else:
                subprocess.Popen(["xdg-open", self.input_folder])
            return "✅ Папка открыта"
        except Exception as e:
            return f"❌ Ошибка: {str(e)}"

    # Справочники, которые оператору нужно регулярно обновлять целиком
    # (присылают из другого отдела) — категория в модалке обновления
    # копирует выбранный файл под точным именем, которое ищет код
    # (main_parser.py / table_parser.py / km_parser.py), так что
    # оператору не нужно знать и не нужно переименовывать файл руками.
    REFERENCE_FILE_TARGETS = {
        "temperature_current": ("Отчёт по температуре (текущий)", "20. Отчет по температуре.xlsx"),
        "temperature_2026": ("Отчёт по температуре (2026)", "20. Отчет по температуре 2026.xlsx"),
        "vm_cost": ("Стоимость ВМ задачи", "Стоимость ВМ задачи (не удалять).xlsx"),
        "mileage": ("Отчёт по километражу", "17. Отчет по километражу.xlsx"),
    }

    def get_reference_update_categories(self):
        return [{"key": key, "label": label} for key, (label, _target) in self.REFERENCE_FILE_TARGETS.items()]

    def update_reference_file(self, category: str) -> str:
        """Открывает диалог выбора файла и копирует его в reference_dir
        под именем, которое ожидает код — чтобы обновление справочника
        (температура, ВМ и т.д.) не требовало ручного переименования."""
        target = self.REFERENCE_FILE_TARGETS.get(category)
        if target is None:
            return "❌ Неизвестная категория справочника"
        label, filename = target

        if self.window is None:
            return "❌ Окно приложения не готово, попробуйте ещё раз"

        try:
            selected = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("Excel файлы (*.xlsx)", "Все файлы (*.*)"),
            )
        except Exception as e:
            return f"❌ Не удалось открыть диалог выбора файла: {e}"

        if not selected:
            return ""

        src_path = Path(selected[0])
        if not src_path.exists():
            return "❌ Выбранный файл не найден"

        dst_path = get_reference_dir() / filename
        try:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
        except Exception as e:
            return f"❌ Не удалось обновить «{label}»: {e}"

        self._clear_reference_caches()
        return f"✅ «{label}» обновлён из файла {src_path.name}\nСохранено как: {dst_path}"

    def _clear_reference_caches(self) -> None:
        """Сбрасывает in-memory кэши справочников, чтобы обновлённый файл
        подхватился сразу, без перезапуска приложения.

        Раньше сбрасывался только _vm_price_df_cache и кэши table_parser —
        категория "mileage" ("17. Отчет по километражу.xlsx") тоже
        обновляема через это меню, но её лист "Лист1" отдельно кэшируется
        в FinalUnifiedParser (_rate_reference_cache, _prayskurant_codes_
        cache, _prayskurant_prices_cache, _prayskurant_41_cache) — эти
        кэши не сбрасывались, и "Проверка расценок"/"Интегральный
        коэффициент" молча продолжали работать по старым данным до
        перезапуска приложения, хотя сообщение об успехе обещало
        обратное. Сбрасываем все известные кэши справочников, а не
        только те, что были нужны для первой (VM/температура) фичи."""
        try:
            from src.extractors.main_parser import WellData, FinalUnifiedParser
            import src.extractors.main_parser as main_parser_module
            WellData._vm_price_df_cache = None
            FinalUnifiedParser._rate_reference_cache = None
            FinalUnifiedParser._party_keywords_cache = None
            FinalUnifiedParser._prayskurant_codes_cache = None
            FinalUnifiedParser._prayskurant_prices_cache = None
            FinalUnifiedParser._prayskurant_41_cache = None
            main_parser_module._contract_coefficients_cache = None
        except Exception:
            pass
        try:
            from src.extractors import table_parser
            table_parser._SHEET_NAMES_CACHE.clear()
            table_parser._SHEET_DF_CACHE.clear()
        except Exception:
            pass

    def pick_and_check_batch(self):
        """Открывает системный диалог выбора нескольких PDF, копирует их
        в input и сразу проверяет всем пакетом, выгружая сводный Excel-отчёт."""
        if self.window is None:
            return "❌ Окно приложения не готово, попробуйте ещё раз"

        try:
            selected = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=("PDF файлы (*.pdf)", "Все файлы (*.*)"),
            )
        except Exception as e:
            return f"❌ Не удалось открыть диалог выбора файлов: {e}"

        if not selected:
            return ""

        copied_paths = []
        for src in selected:
            src_path = Path(src)
            if src_path.suffix.lower() != ".pdf" or not src_path.exists():
                continue
            dst_path = self.input_folder / src_path.name
            try:
                if src_path.resolve() != dst_path.resolve():
                    shutil.copy2(src_path, dst_path)
                copied_paths.append(dst_path)
            except Exception:
                continue

        if not copied_paths:
            return "❌ Среди выбранного не найдено ни одного PDF файла"

        return self._run_batch(copied_paths)

    def _run_batch(self, pdf_paths):
        """Тонкая обёртка над batch_pipeline.run_batch_pipeline() — сам
        разбор пакета живёт там, здесь только форматирование вывода для UI
        и открытие готового отчёта в системном приложении."""
        from src.extractors.batch_pipeline import run_batch_pipeline

        def _on_progress(stage: str, current: int, total: int, filename: str) -> None:
            if self.window is None:
                return
            payload = json.dumps({"stage": stage, "current": current, "total": total, "filename": filename})
            try:
                self.window.evaluate_js(f"window.updateBatchProgress && window.updateBatchProgress({payload})")
            except Exception:
                pass

        result = run_batch_pipeline(pdf_paths, progress_callback=_on_progress)

        output = "🚀 ПАКЕТНАЯ ПРОВЕРКА\n"
        output += f"Файлов в пакете: {len(pdf_paths)} (актов: {len(result.akt_paths)}"
        if result.zayavki:
            output += f", заявок: {len(result.zayavki)}"
        if result.prostoy_files:
            output += f", актов на простой: {len(result.prostoy_files)}"
        output += ")\n"
        if result.prostoy_files:
            output += (
                "⚠️ Автосверка актов на простой с тех.дежурством пока не реализована — "
                f"проверьте вручную: {', '.join(result.prostoy_files)}\n"
            )
        output += f"Папка данных: {self.runtime_root}\n"
        output += "=" * 50 + "\n\n"
        output += result.stdout_text

        if result.stderr_text:
            output += "\n" + "─" * 50 + "\n"
            output += "⚠️  ОШИБКИ:\n"
            output += "─" * 50 + "\n"
            output += result.stderr_text

        output += "\n" + "=" * 50 + "\n"
        if result.report_path:
            output += f"✅ Сводный отчёт сохранён: {result.report_path}\n"
            try:
                if sys.platform == "win32":
                    os.startfile(result.report_path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(result.report_path)])
                else:
                    subprocess.Popen(["xdg-open", str(result.report_path)])
            except Exception:
                pass
        else:
            output += "⚠️ Сводный отчёт не был сформирован (см. ошибки выше)\n"

        return output

    def refresh_files(self):
        if not self.input_folder.exists():
            self.input_folder.mkdir(parents=True, exist_ok=True)
            return []
        
        pdf_files = list(self.input_folder.glob("*.pdf"))
        return [f.name for f in pdf_files]

# HTML интерфейс
def _svg_data_uri(name: str) -> str:
    path = Path(__file__).parent / name
    if not path.exists():
        return ""
    svg = path.read_text(encoding="utf-8")
    return "data:image/svg+xml;utf8," + quote(svg)


def _png_data_uri(name: str) -> str:
    path = Path(__file__).parent / name
    if not path.exists():
        return ""
    import base64
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return "data:image/png;base64," + data

SVG_MAIN = _svg_data_uri("main_parser.svg")
SVG_TABLE = _svg_data_uri("table_parser.svg")
SVG_INTEGRAL = _svg_data_uri("integral.svg")
SVG_FOLDER = _svg_data_uri("folder.svg")
SVG_REFRESH = _svg_data_uri("download_file.svg")
SVG_CLEAR = _svg_data_uri("basket.svg")
SVG_CHECK = _svg_data_uri("check_file.svg")
SVG_LOGO = _svg_data_uri("logo-lu.svg")
SVG_SKV = _svg_data_uri("skvazhina.svg")
SVG_BATCH = _svg_data_uri("batch.svg")
# Юбилейный логотип "35 лет ЛУКОЙЛ" — фон уже удалён (lukoil35-anniversary.png
# сделан из "35 лет.png", присланного пользователем, порогом по белому цвету),
# используется только на заставке при старте.
PNG_ANNIVERSARY35 = _png_data_uri("lukoil35-anniversary.png")

html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AKT-NARYAD VERIFIER • v3.0</title>
    <style>
        :root {
            --bg: #f7f7f5;
            --panel: #ffffff;
            --panel-2: #f2f2ee;
            --text: #1c1c1c;
            --muted: #6b6b6b;
            --accent: #e30613;
            --accent-2: #d3121f;
            --border: #e3e3e3;
        }
        body {
            font-family: "Avenir Next", "Helvetica Neue", "Segoe UI", sans-serif;
            background: radial-gradient(1200px 800px at 20% -10%, #ffffff, #f4f4f0);
            color: var(--text);
            margin: 0;
            padding: 0;
        }
        .app {
            display: grid;
            grid-template-columns: 280px 1fr;
            height: 100vh;
        }
        .sidebar {
            background: var(--panel-2);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
        }
        .sidebar-header {
            padding: 14px 12px 8px 12px;
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            height: 85px;
            box-sizing: border-box;
        }
        .brand {
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 700;
            font-size: 14px;
            letter-spacing: 0.5px;
        }
        .brand img {
            width: 120px;
            height: auto;
        }
        .new-request {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 34px;
            height: 34px;
            border-radius: 10px;
            border: 1px solid var(--border);
            background: #fff;
            cursor: pointer;
            font-weight: 700;
            font-size: 18px;
        }
        .request-list {
            padding: 12px;
            overflow-y: auto;
        }
        .request-item {
            padding: 10px 12px;
            border-radius: 12px;
            cursor: pointer;
            margin-bottom: 8px;
            border: 1px solid transparent;
            background: #fff;
            box-shadow: 0 1px 0 rgba(0,0,0,0.03);
            transition: transform 0.15s ease, border-color 0.15s ease;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .request-item:hover {
            transform: translateY(-1px);
            border-color: var(--border);
        }
        .request-item.active {
            border-color: var(--accent);
            box-shadow: 0 2px 10px rgba(227, 6, 19, 0.15);
        }
        .request-title {
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .request-edit {
            margin-left: auto;
            width: 22px;
            height: 22px;
            border-radius: 6px;
            border: 1px solid var(--border);
            background: #fff;
            cursor: pointer;
            font-size: 12px;
            line-height: 1;
        }
        .request-delete {
            width: 22px;
            height: 22px;
            border-radius: 6px;
            border: 1px solid var(--border);
            background: #fff;
            cursor: pointer;
            font-size: 12px;
            line-height: 1;
        }
        .main {
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        .topbar {
            padding: 22px 20px;
            border-bottom: 1px solid var(--border);
            background: var(--panel);
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 12px;
        }
        .tool-group {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .tool-btn {
            width: 40px;
            height: 40px;
            border-radius: 14px;
            border: none;
            background: #fff;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 6px;
            padding: 0;
            box-sizing: border-box;
            cursor: pointer;
            font-weight: 600;
            font-size: 12px;
            text-align: center;
            transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
        }
        .tool-btn img {
            width: 26px;
            height: 26px;
        }
        .tool-btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(0,0,0,0.08);
        }
        .hint {
            margin-left: auto;
            font-size: 12px;
            color: var(--muted);
            min-width: 240px;
            text-align: right;
        }
        .icon-black {
            filter: grayscale(1) brightness(0);
        }
        .tool-btn.primary {
            border-color: var(--accent);
            box-shadow: inset 0 0 0 1px var(--accent);
        }
        .tool-btn.batch-highlight {
            background: var(--accent);
            animation: batchBtnPulse 2.4s ease-in-out infinite;
        }
        .tool-btn.batch-highlight img {
            filter: brightness(0) invert(1);
        }
        .tool-btn.batch-highlight:hover {
            transform: translateY(-1px) scale(1.05);
        }
        @keyframes batchBtnPulse {
            0%, 100% { box-shadow: 0 4px 14px rgba(227, 6, 19, 0.35); }
            50% { box-shadow: 0 4px 20px rgba(227, 6, 19, 0.7); }
        }
        .tool-btn.start-btn {
            border: 2px solid var(--accent);
            background: transparent;
            box-shadow: none;
        }
        .file-btn {
            position: relative;
        }
        .file-btn select {
            position: absolute;
            inset: 0;
            opacity: 0;
            cursor: pointer;
            pointer-events: none;
        }
        .output {
            flex: 1;
            padding: 0;
            overflow-y: auto;
            background: #fafafa;
            font-family: inherit;
            font-weight: 400;
            font-size: 13px;
            position: relative;
        }
        .output-body {
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }
        .file-card {
            background: #fff;
            border: 1px solid var(--border);
            border-radius: 14px;
            box-shadow: 0 10px 24px rgba(0,0,0,0.06);
            padding: 14px 16px;
        }
        .file-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 10px;
        }
        .file-title-wrap {
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        .file-icon {
            width: 16px;
            height: 16px;
        }
        .file-title {
            font-weight: 700;
            font-size: 15px;
        }
        .pill {
            display: inline-flex;
            align-items: center;
            padding: 4px 8px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 700;
            border: 1px solid var(--border);
            background: #f7f7f7;
        }
        .pill.ok { border-color: #5bb56b; color: #2c6a37; background: #eef9f1; }
        .pill.bad { border-color: #e07b7b; color: #8d2b2b; background: #fdecec; }
        .pill.neutral { border-color: #c9c9c9; color: #666; background: #f2f2f2; }
        .meta-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 6px 14px;
            font-size: 12px;
            color: var(--muted);
            margin-bottom: 10px;
        }
        .meta-grid span {
            color: var(--text);
            font-weight: 600;
        }
        .check-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            padding: 8px 10px;
            border-radius: 10px;
            border: 1px solid var(--border);
            background: #fafafa;
            font-size: 12px;
        }
        .check-row.ok { border-color: #cde9d3; background: #f5fbf6; }
        .check-row.bad { border-color: #f0c7c7; background: #fdf5f5; }
        details.check-detail {
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 6px 10px;
            background: #fafafa;
        }
        details.check-detail.bad {
            border-color: #f0c7c7;
            background: #fdf5f5;
        }
        details.check-detail summary {
            cursor: pointer;
            list-style: none;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            font-weight: 600;
            font-size: 12px;
        }
        details.check-detail summary::-webkit-details-marker {
            display: none;
        }
        .detail-lines {
            margin-top: 8px;
            padding-left: 4px;
            color: var(--muted);
            font-size: 12px;
            white-space: pre-wrap;
        }
        .raw-output {
            white-space: pre-wrap;
            font-size: 12px;
            color: var(--text);
        }
        .spacer {
            height: 16px;
        }
        .loading-indicator {
            display: none;
            position: absolute;
            inset: 0;
            background: rgba(250, 250, 250, 0.75);
            backdrop-filter: blur(2px);
            align-items: center;
            justify-content: center;
        }
        .loading-indicator.active {
            display: flex;
        }
        .modal {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.35);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 10;
        }
        .modal.active {
            display: flex;
        }
        .modal-card {
            width: 520px;
            max-width: calc(100vw - 40px);
            background: #fff;
            border: 1px solid var(--border);
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.18);
            padding: 18px;
        }
        .modal-title {
            font-weight: 700;
            margin-bottom: 12px;
        }
        .modal-list {
            max-height: 240px;
            overflow-y: auto;
            border: 1px solid var(--border);
            border-radius: 10px;
        }
        .modal-item {
            padding: 10px 12px;
            cursor: pointer;
            border-bottom: 1px solid var(--border);
        }
        .modal-item:last-child {
            border-bottom: none;
        }
        .modal-item.active {
            background: #f7f1f1;
            border-left: 3px solid var(--accent);
        }
        .modal-actions {
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            margin-top: 14px;
        }
        .modal-btn {
            padding: 8px 14px;
            border-radius: 10px;
            border: 1px solid var(--border);
            background: #fff;
            cursor: pointer;
            font-weight: 600;
        }
        .modal-btn.primary {
            border-color: var(--accent);
        }
        .toast {
            position: absolute;
            top: 64px;
            right: 20px;
            background: #fff;
            border: 1px solid var(--border);
            border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.12);
            padding: 12px 14px;
            min-width: 260px;
            max-width: 420px;
            display: none;
            z-index: 9;
        }
        .toast.active {
            display: block;
            animation: toastIn 0.2s ease-out;
        }
        .toast-title {
            font-weight: 700;
            margin-bottom: 6px;
        }
        .toast-list {
            max-height: 140px;
            overflow-y: auto;
            font-size: 12px;
            color: var(--muted);
        }
        @keyframes toastIn {
            from { transform: translateY(-6px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        .spinner {
            width: 28px;
            height: 28px;
            border: 3px solid #ddd;
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .splash {
            position: fixed;
            inset: 0;
            z-index: 999;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background:
                radial-gradient(1100px 700px at 50% -10%, rgba(227, 6, 19, 0.35), transparent 60%),
                linear-gradient(155deg, #1a0002 0%, #3d0308 22%, #7a0812 42%, #b8101c 58%, #7a0812 74%, #1a0002 100%);
            background-size: 200% 200%;
            animation: splashGradient 6s ease-in-out infinite;
            transition: opacity 0.5s ease, visibility 0.5s ease;
        }
        .splash.hidden {
            opacity: 0;
            visibility: hidden;
            pointer-events: none;
        }
        @keyframes splashGradient {
            0% { background-position: 0% 30%; }
            50% { background-position: 100% 70%; }
            100% { background-position: 0% 30%; }
        }
        .splash-logo-wrap {
            background: #fff;
            border-radius: 22px;
            padding: 22px 34px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.45);
            animation: splashPulse 2.2s ease-in-out infinite;
        }
        .splash-logo-wrap img {
            width: 220px;
            height: auto;
            display: block;
        }
        @keyframes splashPulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.035); }
        }
        .splash-title {
            margin-top: 28px;
            color: #fff;
            font-weight: 700;
            font-size: 22px;
            letter-spacing: 1px;
            text-shadow: 0 2px 12px rgba(0, 0, 0, 0.5);
        }
        .splash-subtitle {
            margin-top: 8px;
            color: rgba(255, 255, 255, 0.75);
            font-size: 13px;
            letter-spacing: 2px;
            text-transform: uppercase;
        }
        .splash-spinner {
            margin-top: 34px;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            border: 3px solid rgba(255, 255, 255, 0.25);
            border-top-color: #fff;
            animation: spin 0.9s linear infinite;
        }
        .splash-dots {
            margin-top: 14px;
            color: rgba(255, 255, 255, 0.6);
            font-size: 12px;
            letter-spacing: 0.5px;
        }
        .splash-anniversary {
            margin-bottom: 18px;
            animation: splashPulse 2.2s ease-in-out infinite;
        }
        .splash-anniversary img {
            width: 110px;
            height: auto;
            display: block;
            filter: drop-shadow(0 6px 18px rgba(0, 0, 0, 0.5));
        }
        .firework-layer {
            position: absolute;
            inset: 0;
            overflow: hidden;
            pointer-events: none;
            z-index: -1;
        }
        .firework-particle {
            position: absolute;
            width: 6px;
            height: 6px;
            border-radius: 50%;
            box-shadow: 0 0 6px 2px currentColor;
            animation: fireworkBurst 900ms ease-out forwards;
        }
        @keyframes fireworkBurst {
            0% { transform: translate(0, 0) scale(1); opacity: 1; }
            100% { transform: translate(var(--dx), var(--dy)) scale(0.2); opacity: 0; }
        }

        .batch-progress-overlay {
            position: fixed;
            inset: 0;
            z-index: 900;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(20, 4, 6, 0.55);
            backdrop-filter: blur(3px);
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.25s ease, visibility 0.25s ease;
        }
        .batch-progress-overlay.active {
            opacity: 1;
            visibility: visible;
        }
        .batch-progress-card {
            background: var(--panel);
            border-radius: 24px;
            padding: 40px 50px;
            box-shadow: 0 30px 80px rgba(0, 0, 0, 0.4);
            display: flex;
            flex-direction: column;
            align-items: center;
            min-width: 260px;
        }
        .batch-progress-ring-wrap {
            position: relative;
            width: 160px;
            height: 160px;
        }
        .batch-progress-ring-wrap svg {
            transform: rotate(-90deg);
        }
        .batch-progress-ring-bg {
            fill: none;
            stroke: var(--border);
            stroke-width: 10;
        }
        .batch-progress-ring-fg {
            fill: none;
            stroke: var(--accent);
            stroke-width: 10;
            stroke-linecap: round;
            transition: stroke-dashoffset 0.35s ease;
        }
        .batch-progress-percent {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 32px;
            font-weight: 700;
            color: var(--text);
        }
        .batch-progress-stage {
            margin-top: 24px;
            font-size: 14px;
            font-weight: 600;
            color: var(--text);
            letter-spacing: 0.3px;
            text-align: center;
        }
        .batch-progress-filename {
            margin-top: 6px;
            font-size: 12px;
            color: var(--muted);
            max-width: 300px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
    </style>
</head>
<body>
    <div class="splash" id="splashScreen">
        <div class="firework-layer" id="fireworkLayer"></div>
        <div class="splash-anniversary">
            <img src="__PNG_ANNIVERSARY35__" alt="35 лет ЛУКОЙЛ">
        </div>
        <div class="splash-logo-wrap">
            <img src="__SVG_LOGO__" alt="ЛУКОЙЛ">
        </div>
        <div class="splash-title">AKT-NARYAD VERIFIER</div>
        <div class="splash-subtitle">Система анализа актов-нарядов</div>
        <div class="splash-spinner"></div>
        <div class="splash-dots" id="splashStatus">Загрузка...</div>
    </div>
    <div class="batch-progress-overlay" id="batchProgressOverlay">
        <div class="batch-progress-card">
            <div class="batch-progress-ring-wrap">
                <svg width="160" height="160" viewBox="0 0 160 160">
                    <circle class="batch-progress-ring-bg" cx="80" cy="80" r="70"></circle>
                    <circle class="batch-progress-ring-fg" id="batchProgressRing" cx="80" cy="80" r="70"
                        stroke-dasharray="439.82" stroke-dashoffset="439.82"></circle>
                </svg>
                <div class="batch-progress-percent" id="batchProgressPercent">0%</div>
            </div>
            <div class="batch-progress-stage" id="batchProgressStage">Подготовка…</div>
            <div class="batch-progress-filename" id="batchProgressFilename"></div>
        </div>
    </div>
    <div class="app">
        <aside class="sidebar">
            <div class="sidebar-header">
                <div class="brand">
                    <img src="__SVG_LOGO__" alt="Logo">
                </div>
                <button class="new-request" onclick="createNewRequest()" aria-label="Новый запрос">+</button>
            </div>
            <div class="request-list" id="requestList"></div>
        </aside>
        <main class="main">
            <header class="topbar">
                <div class="tool-group">
                    <button class="tool-btn" data-hint="Нажмите, чтобы запустить основной парсер" onclick="openMainParserModal()" aria-label="Пуск">
                        <img src="__SVG_MAIN__" alt="">
                    </button>
                    <div class="tool-btn file-btn" data-hint="Нажмите, чтобы выбрать файл" aria-label="Выбор файла" onclick="openFilePicker()">
                        <img src="__SVG_CHECK__" alt="">
                        <select id="fileSelect"></select>
                    </div>
                    <button class="tool-btn batch-highlight" data-hint="👉 Основной способ проверки: нажмите, чтобы загрузить пакет файлов, проверить все и выгрузить Excel-отчёт" onclick="runBatchCheck()" aria-label="Пакетная проверка (основной способ)">
                        <img src="__SVG_BATCH__" alt="">
                    </button>
                    <button class="tool-btn" data-hint="Нажмите, чтобы открыть папку input" onclick="openFolder()" aria-label="Открыть папку">
                        <img src="__SVG_FOLDER__" class="icon-black" alt="">
                    </button>
                    <button class="tool-btn" data-hint="Нажмите, чтобы обновить справочник (температура, ВМ, километраж)" onclick="openReferenceUpdateModal()" aria-label="Обновить справочник">
                        <img src="__SVG_TABLE__" class="icon-black" alt="">
                    </button>
                    <button class="tool-btn" data-hint="Нажмите, чтобы обновить список файлов" onclick="refreshFiles()" aria-label="Обновить">
                        <img src="__SVG_REFRESH__" alt="">
                    </button>
                    <button class="tool-btn" data-hint="Нажмите, чтобы очистить вывод" onclick="clearOutput()" aria-label="Очистить">
                        <img src="__SVG_CLEAR__" alt="">
                    </button>
                </div>
                <div class="hint" id="headerHint"></div>
            </header>
            <div class="toast" id="fileToast">
                <div class="toast-title" id="toastTitle">Файлы</div>
                <div class="toast-list" id="toastList"></div>
            </div>
            <div class="output" id="output">
                <div class="output-body" id="outputBody"></div>
                <div class="loading-indicator" id="loadingIndicator">
                    <div class="spinner"></div>
                </div>
            </div>
            <div class="modal" id="fileModal">
                <div class="modal-card">
                    <div class="modal-title">Выберите файл для запуска</div>
                    <div class="modal-list" id="modalFileList"></div>
                    <div class="modal-actions">
                        <button class="modal-btn" onclick="closeFileModal()">Отмена</button>
                        <button class="modal-btn primary" onclick="confirmFileModal()">Запустить</button>
                    </div>
                </div>
            </div>
            <div class="modal" id="referenceModal">
                <div class="modal-card">
                    <div class="modal-title">Что обновляем?</div>
                    <div class="modal-list" id="referenceCategoryList"></div>
                    <div class="modal-actions">
                        <button class="modal-btn" onclick="closeReferenceModal()">Отмена</button>
                    </div>
                </div>
            </div>
        </main>
    </div>
    
    <script>
        function updateStatus(text) {}

        let hintTimer = null;
        function setHint(text) {
            const hint = document.getElementById('headerHint');
            if (!hint) return;
            hint.textContent = text || '';
        }

        function setHintLoading(text) {
            const hint = document.getElementById('headerHint');
            if (!hint) return;
            if (hintTimer) clearInterval(hintTimer);
            let dots = 0;
            hint.textContent = text;
            hintTimer = setInterval(() => {
                dots = (dots + 1) % 4;
                hint.textContent = text + '.'.repeat(dots);
            }, 400);
        }

        function clearHintLoading() {
            if (hintTimer) {
                clearInterval(hintTimer);
                hintTimer = null;
            }
            setHint('');
        }

        function bindHints() {
            document.querySelectorAll('[data-hint]').forEach(btn => {
                btn.addEventListener('mouseenter', () => setHint(btn.getAttribute('data-hint') || ''));
                btn.addEventListener('mouseleave', () => setHint(''));
            });
        }

        function setLoading(isLoading) {
            const indicator = document.getElementById('loadingIndicator');
            if (indicator) {
                indicator.classList.toggle('active', isLoading);
            }
        }

        
        let requests = [];
        let activeRequestId = null;
        let requestCounter = 1;

        function renderRequestList() {
            const list = document.getElementById('requestList');
            list.innerHTML = '';
            requests.forEach(req => {
                const item = document.createElement('div');
                item.className = 'request-item' + (req.id === activeRequestId ? ' active' : '');
                const title = document.createElement('div');
                title.className = 'request-title';
                title.textContent = req.title;
                const edit = document.createElement('button');
                edit.className = 'request-edit';
                edit.textContent = '✎';
                edit.onclick = (e) => {
                    e.stopPropagation();
                    startInlineRename(req.id, title);
                };
                const del = document.createElement('button');
                del.className = 'request-delete';
                del.textContent = '✕';
                del.onclick = (e) => {
                    e.stopPropagation();
                    deleteRequest(req.id);
                };
                item.onclick = () => setActiveRequest(req.id);
                title.ondblclick = () => startInlineRename(req.id, title);
                item.appendChild(title);
                item.appendChild(edit);
                item.appendChild(del);
                list.appendChild(item);
            });
        }

        function setActiveRequest(id) {
            activeRequestId = id;
            renderRequestList();
            renderOutput();
        }

        function createNewRequest() {
            const title = `Запрос ${requestCounter++}`;
            const id = Date.now() + Math.random();
            requests.unshift({ id, title, log: '' });
            setActiveRequest(id);
            return id;
        }

        function deleteRequest(id) {
            const idx = requests.findIndex(r => r.id === id);
            if (idx === -1) return;
            requests.splice(idx, 1);
            if (activeRequestId === id) {
                activeRequestId = requests.length ? requests[0].id : null;
            }
            renderRequestList();
            renderOutput();
        }

        function startInlineRename(id, itemEl) {
            const req = requests.find(r => r.id === id);
            if (!req || !itemEl) return;

            const input = document.createElement('input');
            input.type = 'text';
            input.value = '';
            input.placeholder = '';
            input.style.width = '100%';
            input.style.border = 'none';
            input.style.outline = 'none';
            input.style.background = 'transparent';
            input.style.font = 'inherit';

            const prevTitle = req.title;
            itemEl.textContent = '';
            itemEl.appendChild(input);
            input.focus();

            const finalize = (commit) => {
                const next = input.value.trim();
                if (commit && next) {
                    req.title = next;
                } else {
                    req.title = prevTitle;
                }
                renderRequestList();
            };

            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') finalize(true);
                if (e.key === 'Escape') finalize(false);
            });
            input.addEventListener('blur', () => finalize(false));
        }

        function getActiveRequest() {
            if (!activeRequestId && requests.length === 0) {
                createNewRequest();
            }
            return requests.find(r => r.id === activeRequestId);
        }

        function renderOutput() {
            const output = document.getElementById('outputBody');
            const req = getActiveRequest();
            const text = req ? (req.log || '') : '';
            if (!text) {
                output.textContent = '';
                return;
            }
            output.innerHTML = renderRuns(text);
            output.scrollTop = output.scrollHeight;
        }

        function appendOutput(text) {
            const req = getActiveRequest();
            if (!req) return;
            req.log = (req.log ? req.log + '\\n\\n' : '') + text;
            renderOutput();
        }
        
        function updateFileList(files) {
            const fileList = document.getElementById('fileList');
            const fileSelect = document.getElementById('fileSelect');
            const previous = fileSelect ? fileSelect.value : '';
            
            if (fileSelect) {
                let options = '<option value="">Все файлы</option>';
                files.forEach(file => {
                    options += `<option value="${file}">${file}</option>`;
                });
                fileSelect.innerHTML = options;
                if (previous) fileSelect.value = previous;
            }
        }

        function escapeHtml(text) {
            return text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        }

        function renderStructuredOutput(text) {
            if (!text) return `<div class="raw-output"></div>`;
            if (text.includes('.pdf:')) return renderMainBlocks(text);
            if (text.includes('Отчет по температуре:')) return renderTempBlocks(text);
            if (text.includes('🧮 Рассчитанный коэффициент')) return renderIntegralBlocks(text);
            if (text.includes('Отчет по километражу:')) return renderKmBlocks(text);
            return `<div class="raw-output">${escapeHtml(text)}</div>`;
        }

        function renderRuns(text) {
            if (!text) return `<div class="raw-output"></div>`;
            const runParts = text.split(/\\n(?=🚀\\sЗАПУСК)/g).filter(p => p.trim());
            return runParts.map(runText => {
                const sections = runText.split(/\\n===\\s+/).filter(s => s.trim());
                if (sections.length <= 1) {
                    return renderStructuredOutput(runText);
                }
                return sections.map((section, idx) => {
                    let body = section;
                    if (idx > 0) body = "=== " + section;
                    body = body.replace(/^===.*?\\n/, '').trim();
                    return renderStructuredOutput(body);
                }).join('');
            }).join('');
        }

        function renderMainBlocks(text) {
            const blocks = text.split(/\\n(?=[^\\n]*\\.pdf:)/g).filter(b => b.trim());
            let html = '';
            blocks.forEach(block => {
                const lines = block.split('\\n').filter(l => l.trim() !== '');
                if (!lines.length) return;
                const title = lines[0].replace(':', '').trim();
                const meta = [];
                const checks = [];
                for (let i = 1; i < lines.length; i++) {
                    const line = lines[i];
                    if (line.startsWith('  ') && line.includes(':') && !line.includes('✅') && !line.includes('❌')) {
                        const lower = line.toLowerCase();
                        if (lower.includes('данных нет') || lower.includes('не найдено') || lower.includes('не найдены')) {
                            const label = line.trim().split(':')[0];
                            checks.push({ label, status: 'neutral', details: ['Информация отсутствует'] });
                            continue;
                        }
                    }
                    if (line.startsWith('  ') && (line.includes('✅') || line.includes('❌'))) {
                        const status = line.includes('✅') ? 'ok' : 'bad';
                        const label = line.trim();
                        const details = [];
                        let j = i + 1;
                        while (j < lines.length && lines[j].startsWith('    ')) {
                            details.push(lines[j].trim());
                            j++;
                        }
                        checks.push({ label, status, details });
                        i = j - 1;
                        continue;
                    }
                    if (line.startsWith('  ') && line.includes(':')) {
                        meta.push(line.trim());
                    }
                }

                const checkHtml = checks.map(ch => {
                    const pill = `<span class="pill ${ch.status}">${ch.status === 'ok' ? 'OK' : ch.status === 'bad' ? 'НЕ СХОД.' : 'ИНФО'}</span>`;
                    if (ch.details.length) {
                        let detailText = ch.details.join('\\n');
                        if (ch.label.includes('Цена ВМ')) {
                            const actLine = ch.details.find(l => l.startsWith('Цена в акте'));
                            const minLine = ch.details.find(l => l.startsWith('Стоимость 1 отв. при min плотности'));
                            if (actLine && minLine) {
                                const prefix = ch.status === 'ok' ? '✅ ' : '❌ ';
                                detailText = `${prefix}Сравниваем строки:\\n• ${actLine}\\n• ${minLine}\\n\\n` + detailText;
                            }
                        }
                        return `
                            <details class="check-detail ${ch.status}">
                                <summary>${escapeHtml(ch.label)} ${pill}</summary>
                                <div class="detail-lines">${escapeHtml(detailText)}</div>
                            </details>
                        `;
                    }
                    return `
                        <details class="check-detail ${ch.status}">
                            <summary>${escapeHtml(ch.label)} ${pill}</summary>
                            <div class="detail-lines">Нет подробностей</div>
                        </details>
                    `;
                }).join('');

                const metaHtml = meta.slice(0, 6).map(m => {
                    const [k, ...rest] = m.split(':');
                    return `<div>${escapeHtml(k)}: <span>${escapeHtml(rest.join(':').trim())}</span></div>`;
                }).join('');

                const overallBad = checks.some(c => c.status === 'bad');
                const overallPill = `<span class="pill ${overallBad ? 'bad' : 'ok'}">${overallBad ? 'ЕСТЬ РАСХ.' : 'ВСЕ ОК'}</span>`;

                html += `
                    <div class="file-card">
                        <div class="file-header">
                        <div class="file-title-wrap">
                            <img class="file-icon" src="__SVG_SKV__" alt="">
                            <div class="file-title">${escapeHtml(title)}</div>
                        </div>
                            ${overallPill}
                        </div>
                        <div class="meta-grid">${metaHtml}</div>
                        <div class="check-list">${checkHtml}</div>
                    </div>
                `;
            });
            return html || `<div class="raw-output">${escapeHtml(text)}</div>`;
        }

        function renderTempBlocks(text) {
            const blocks = text.split(/Отчет по температуре:\\s*/).filter(b => b.trim());
            let html = '';
            blocks.forEach(block => {
                const lines = block.split('\\n').filter(l => l.trim() !== '');
                if (!lines.length) return;
                const title = lines[0].trim();
                const details = lines.slice(1).map(l => l.trim());
                const statusLine = details.find(l => l.includes('РЕЗУЛЬТАТ'));
                const status = statusLine && statusLine.includes('✅') ? 'ok' : (statusLine && statusLine.includes('❌') ? 'bad' : 'neutral');
                const pill = `<span class="pill ${status}">${status === 'ok' ? 'OK' : status === 'bad' ? 'НЕ СХОД.' : 'ИНФО'}</span>`;
                html += `
                    <div class="file-card">
                        <div class="file-header">
                            <div class="file-title-wrap">
                                <img class="file-icon" src="__SVG_SKV__" alt="">
                                <div class="file-title">${escapeHtml(title)}</div>
                            </div>
                            ${pill}
                        </div>
                        <details class="check-detail ${status}">
                            <summary>Отчет по температуре ${pill}</summary>
                            <div class="detail-lines">${escapeHtml(details.join('\\n'))}</div>
                        </details>
                    </div>
                `;
            });
            return html || `<div class="raw-output">${escapeHtml(text)}</div>`;
        }

        function renderIntegralBlocks(text) {
            const blocks = text.split(/\\n(?=[^\\n].*\\.pdf)/g).filter(b => b.trim());
            let html = '';
            blocks.forEach(block => {
                const lines = block.split('\\n').filter(l => l.trim() !== '');
                if (!lines.length) return;
                const title = lines[0].trim();
                const details = lines.slice(1).map(l => l.trim());
                const statusLine = details.find(l => l.includes('Совпадение') || l.includes('Несовпадение'));
                const status = statusLine && statusLine.includes('СХОД') ? 'ok' : (statusLine && statusLine.includes('НЕ СХОД') ? 'bad' : 'neutral');
                const pill = `<span class="pill ${status}">${status === 'ok' ? 'OK' : status === 'bad' ? 'НЕ СХОД.' : 'ИНФО'}</span>`;
                html += `
                    <div class="file-card">
                        <div class="file-header">
                            <div class="file-title-wrap">
                                <img class="file-icon" src="__SVG_SKV__" alt="">
                                <div class="file-title">${escapeHtml(title)}</div>
                            </div>
                            ${pill}
                        </div>
                        <details class="check-detail ${status}">
                            <summary>Интегральный коэффициент ${pill}</summary>
                            <div class="detail-lines">${escapeHtml(details.join('\\n'))}</div>
                        </details>
                    </div>
                `;
            });
            return html || `<div class="raw-output">${escapeHtml(text)}</div>`;
        }

        function renderKmBlocks(text) {
            const blocks = text.split(/Отчет по километражу:\\s*/).filter(b => b.trim());
            let html = '';
            blocks.forEach(block => {
                const lines = block.split('\\n').filter(l => l.trim() !== '');
                if (!lines.length) return;
                const title = lines[0].replace(':', '').trim();
                const details = lines.slice(1).map(l => l.trim());
                const statusLine = details.find(l => l.includes('Результат'));
                const status = statusLine && statusLine.includes('✅') ? 'ok' : (statusLine && statusLine.includes('❌') ? 'bad' : 'neutral');
                const pill = `<span class="pill ${status}">${status === 'ok' ? 'OK' : status === 'bad' ? 'НЕ СХОД.' : 'ИНФО'}</span>`;
                html += `
                    <div class="file-card">
                        <div class="file-header">
                            <div class="file-title-wrap">
                                <img class="file-icon" src="__SVG_SKV__" alt="">
                                <div class="file-title">${escapeHtml(title)}</div>
                            </div>
                            ${pill}
                        </div>
                        <details class="check-detail ${status}">
                            <summary>Отчет по километражу ${pill}</summary>
                            <div class="detail-lines">${escapeHtml(details.join('\\n'))}</div>
                        </details>
                    </div>
                `;
            });
            return html || `<div class="raw-output">${escapeHtml(text)}</div>`;
        }


        function getSelectedFile() {
            const select = document.getElementById('fileSelect');
            return select ? select.value : '';
        }
        
        async function runMainParser() {
            setLoading(true);
            setHintLoading('Анализ документа ...');
            const result = await pywebview.api.run_main_parser(getSelectedFile());
            appendOutput(result);
            setLoading(false);
            clearHintLoading();
            refreshFiles();
        }
        
        async function runTableParser() {
            setLoading(true);
            setHintLoading('Проверка температуры');
            const result = await pywebview.api.run_table_parser(getSelectedFile());
            appendOutput(result);
            setLoading(false);
            clearHintLoading();
            refreshFiles();
        }
        
        async function runIntegralCalculator() {
            setLoading(true);
            setHintLoading('Расчет коэффициента');
            const result = await pywebview.api.run_integral_calculator(getSelectedFile());
            appendOutput(result);
            setLoading(false);
            clearHintLoading();
            refreshFiles();
        }

        const BATCH_RING_CIRCUMFERENCE = 439.82;
        const BATCH_STAGE_LABELS = {
            classify: 'Классификация файлов',
            parse: 'Разбор акт-нарядов',
            report: 'Формирование отчёта',
        };

        function showBatchProgress() {
            const overlay = document.getElementById('batchProgressOverlay');
            if (!overlay) return;
            setBatchProgressUI(0, 'Подготовка…', '');
            overlay.classList.add('active');
        }

        function hideBatchProgress() {
            const overlay = document.getElementById('batchProgressOverlay');
            if (overlay) overlay.classList.remove('active');
        }

        function setBatchProgressUI(percent, stageText, filename) {
            const ring = document.getElementById('batchProgressRing');
            const percentEl = document.getElementById('batchProgressPercent');
            const stageEl = document.getElementById('batchProgressStage');
            const fileEl = document.getElementById('batchProgressFilename');
            if (ring) {
                ring.style.strokeDashoffset = String(BATCH_RING_CIRCUMFERENCE * (1 - percent / 100));
            }
            if (percentEl) percentEl.textContent = Math.round(percent) + '%';
            if (stageEl) stageEl.textContent = stageText;
            if (fileEl) fileEl.textContent = filename || '';
        }

        window.updateBatchProgress = function (data) {
            const total = data.total || 1;
            const current = data.current || 0;
            const percent = Math.min(100, Math.round((current / total) * 100));
            const label = BATCH_STAGE_LABELS[data.stage] || 'Обработка';
            setBatchProgressUI(percent, `${label} (${current}/${total})`, data.filename || '');
        };

        async function runBatchCheck() {
            setLoading(true);
            setHintLoading('Пакетная проверка');
            showBatchProgress();
            let result = '';
            try {
                result = await pywebview.api.pick_and_check_batch();
            } finally {
                setLoading(false);
                clearHintLoading();
                hideBatchProgress();
            }
            if (!result) return;
            appendOutput(result);
            refreshFiles();
        }

        
        async function openFolder() {
            setLoading(true);
            setHintLoading('Открытие папки');
            await pywebview.api.open_folder();
            setLoading(false);
            clearHintLoading();
        }
        
        async function refreshFiles() {
            const files = await pywebview.api.refresh_files();
            updateFileList(files);
            showFilesToast(files);
            return files;
        }

        let toastTimer = null;
        function showFilesToast(files) {
            const toast = document.getElementById('fileToast');
            const title = document.getElementById('toastTitle');
            const list = document.getElementById('toastList');
            if (!toast || !title || !list) return;
            const count = files.length;
            title.textContent = `Найдено файлов: ${count}`;
            if (count === 0) {
                list.textContent = 'Нет PDF файлов';
            } else {
                list.innerHTML = files.map(f => `<div>• ${f}</div>`).join('');
            }
            toast.classList.add('active');
            if (toastTimer) clearTimeout(toastTimer);
            toastTimer = setTimeout(() => {
                toast.classList.remove('active');
            }, 5000);
        }

        async function openFilePicker() {
            setHintLoading('Выбор файла');
            const files = await refreshFiles();
            clearHintLoading();
            if (!files) return;
            const count = files.length;
            if (count === 0) {
                alert('В папке input нет PDF файлов');
                return;
            }
            const fileList = files.map((f, i) => `${i + 1}. ${f}`).join('\\n');
            const input = prompt(`В папке ${count} файлов.\\nВыберите номер файла:\\n${fileList}`);
            if (!input) return;
            const idx = parseInt(input, 10);
            if (!Number.isFinite(idx) || idx < 1 || idx > count) return;
            const selected = files[idx - 1];
            const select = document.getElementById('fileSelect');
            if (select) select.value = selected;
            createNewRequestWithTitle(selected);
        }

        let modalSelectedFile = '';
        function openMainParserModal() {
            openFileModal();
        }

        function openFileModal() {
            const modal = document.getElementById('fileModal');
            const list = document.getElementById('modalFileList');
            if (!modal || !list) return;
            list.innerHTML = 'Загрузка...';
            modalSelectedFile = '';
            modal.classList.add('active');
            refreshFiles().then(files => {
                if (!files || files.length === 0) {
                    list.innerHTML = '<div class="modal-item">Нет PDF файлов</div>';
                    return;
                }
                list.innerHTML = '';
                files.forEach(file => {
                    const item = document.createElement('div');
                    item.className = 'modal-item';
                    item.textContent = file;
                    item.onclick = () => {
                        modalSelectedFile = file;
                        list.querySelectorAll('.modal-item').forEach(el => el.classList.remove('active'));
                        item.classList.add('active');
                    };
                    list.appendChild(item);
                });
            });
        }

        function closeFileModal() {
            const modal = document.getElementById('fileModal');
            if (modal) modal.classList.remove('active');
        }

        function confirmFileModal() {
            if (!modalSelectedFile) return;
            const select = document.getElementById('fileSelect');
            if (select) select.value = modalSelectedFile;
            closeFileModal();
            runMainParser();
        }

        function openReferenceUpdateModal() {
            const modal = document.getElementById('referenceModal');
            const list = document.getElementById('referenceCategoryList');
            if (!modal || !list) return;
            list.innerHTML = 'Загрузка...';
            modal.classList.add('active');
            pywebview.api.get_reference_update_categories().then(categories => {
                if (!categories || categories.length === 0) {
                    list.innerHTML = '<div class="modal-item">Категории не найдены</div>';
                    return;
                }
                list.innerHTML = '';
                categories.forEach(cat => {
                    const item = document.createElement('div');
                    item.className = 'modal-item';
                    item.textContent = cat.label;
                    item.onclick = () => selectReferenceCategory(cat.key);
                    list.appendChild(item);
                });
            });
        }

        function closeReferenceModal() {
            const modal = document.getElementById('referenceModal');
            if (modal) modal.classList.remove('active');
        }

        async function selectReferenceCategory(key) {
            closeReferenceModal();
            setLoading(true);
            setHintLoading('Обновление справочника');
            let result = '';
            try {
                result = await pywebview.api.update_reference_file(key);
            } finally {
                setLoading(false);
                clearHintLoading();
            }
            if (!result) return;
            appendOutput(result);
        }

        function createNewRequestWithTitle(title) {
            const id = Date.now() + Math.random();
            requests.unshift({ id, title, log: '' });
            setActiveRequest(id);
            return id;
        }
        
        function clearOutput() {
            setLoading(true);
            setHintLoading('Очистка вывода');
            const req = getActiveRequest();
            if (req) {
                req.log = '';
                renderOutput();
            }
            setLoading(false);
            clearHintLoading();
        }
        
        function hideSplash() {
            const splash = document.getElementById('splashScreen');
            if (splash) splash.classList.add('hidden');
            stopFireworks();
        }

        let fireworkTimer = null;
        function spawnFirework() {
            const layer = document.getElementById('fireworkLayer');
            if (!layer) return;
            const colors = ['#ff3b30', '#ffd60a', '#ffffff', '#ff6b6b', '#ffb700'];
            const x = 12 + Math.random() * 76;
            const y = 10 + Math.random() * 55;
            const particleCount = 14;
            for (let i = 0; i < particleCount; i++) {
                const p = document.createElement('div');
                p.className = 'firework-particle';
                const angle = (i / particleCount) * 2 * Math.PI;
                const dist = 40 + Math.random() * 40;
                p.style.setProperty('--dx', (Math.cos(angle) * dist) + 'px');
                p.style.setProperty('--dy', (Math.sin(angle) * dist) + 'px');
                p.style.left = x + '%';
                p.style.top = y + '%';
                p.style.color = colors[i % colors.length];
                p.style.background = colors[i % colors.length];
                layer.appendChild(p);
                p.addEventListener('animationend', () => p.remove());
            }
        }
        function startFireworks() {
            if (fireworkTimer) return;
            spawnFirework();
            fireworkTimer = setInterval(spawnFirework, 700);
        }
        function stopFireworks() {
            if (fireworkTimer) {
                clearInterval(fireworkTimer);
                fireworkTimer = null;
            }
            const layer = document.getElementById('fireworkLayer');
            if (layer) layer.innerHTML = '';
        }

        // Загружаем файлы при старте
        async function initApp() {
            startFireworks();
            const splashStart = Date.now();
            const splashStatus = document.getElementById('splashStatus');
            const setSplashStatus = (text) => { if (splashStatus) splashStatus.textContent = text; };

            try {
                if (requests.length === 0) {
                    createNewRequest();
                } else {
                    renderRequestList();
                    renderOutput();
                }
                bindHints();
                setSplashStatus('Проверка файлов...');
                await refreshFiles();
                setTimeout(() => {
                    if (requests.length === 0) {
                        createNewRequest();
                    }
                }, 50);
            } catch (e) {
                console.error(e);
            } finally {
                setSplashStatus('Готово');
                // Держим экран минимум ~900мс, чтобы не мигал на быстром старте
                const elapsed = Date.now() - splashStart;
                setTimeout(hideSplash, Math.max(0, 3000 - elapsed));
            }
        }

        window.addEventListener('DOMContentLoaded', initApp);
    </script>
</body>
</html>
"""

html = html.replace("__SVG_MAIN__", SVG_MAIN)
html = html.replace("__SVG_TABLE__", SVG_TABLE)
html = html.replace("__SVG_INTEGRAL__", SVG_INTEGRAL)
html = html.replace("__SVG_FOLDER__", SVG_FOLDER)
html = html.replace("__SVG_REFRESH__", SVG_REFRESH)
html = html.replace("__SVG_CLEAR__", SVG_CLEAR)
html = html.replace("__SVG_CHECK__", SVG_CHECK)
html = html.replace("__SVG_LOGO__", SVG_LOGO)
html = html.replace("__SVG_SKV__", SVG_SKV)
html = html.replace("__SVG_BATCH__", SVG_BATCH)
html = html.replace("__PNG_ANNIVERSARY35__", PNG_ANNIVERSARY35)


def _run_cli_mode(argv):
    run_check = "--self-check" in argv
    run_smoke = "--smoke-test" in argv
    run_verify_real = "--verify-real-input" in argv
    if not run_check and not run_smoke and not run_verify_real:
        return None

    _configure_console_streams()
    exit_code = 0

    if run_check:
        check_result = run_self_check(write_logs=True)
        print(format_self_check_report(check_result, with_hints=True))
        if check_result.get("errors", 0):
            exit_code = 2

    if run_smoke:
        smoke_result = run_smoke_test(max_files=2)
        print(format_smoke_report(smoke_result))
        if not smoke_result.get("ok"):
            exit_code = 2

    if run_verify_real:
        from tools.verify_real_input import run as run_verify_real_input
        if run_verify_real_input() != 0:
            exit_code = 2

    return exit_code


if __name__ == "__main__":
    cli_exit = _run_cli_mode(sys.argv[1:])
    if cli_exit is not None:
        raise SystemExit(cli_exit)

    api = API()
    
    # Создаем окно
    icon_candidates = [
        Path(__file__).parent / "lukoil-app.ico",
        Path(__file__).parent / "lukoil35.ico",
        Path(__file__).parent / "lukoil-desk.ico",
    ]
    icon_path = ""
    for candidate in icon_candidates:
        if candidate.exists():
            icon_path = str(candidate)
            break
    def _set_taskbar_icon():
        if sys.platform != "win32":
            return
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        user32 = ctypes.windll.user32
        hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
        if not hicon:
            return
        pid = os.getpid()
        handles = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_proc(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            current_pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(current_pid))
            if current_pid.value == pid:
                handles.append(hwnd)
            return True

        for _ in range(15):
            handles.clear()
            user32.EnumWindows(enum_proc, 0)
            if handles:
                break
            time.sleep(0.2)

        for hwnd in handles:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LUKOIL.AktNaryad.Verifier")
    try:
        create_kwargs = dict(
            title="AKT-NARYAD VERIFIER • v3.0",
            html=html,
            js_api=api,
            width=1100,
            height=900,
            resizable=True,
            text_select=True,
        )
        if icon_path:
            create_kwargs["icon"] = icon_path
        window = webview.create_window(**create_kwargs)
        start_icon = None
    except TypeError:
        window = webview.create_window(
            "AKT-NARYAD VERIFIER • v3.0",
            html=html,
            js_api=api,
            width=1100,
            height=900,
            resizable=True,
            text_select=True
        )
        start_icon = icon_path

    api.window = window

    webview.start(_set_taskbar_icon, debug=False, icon=start_icon)
