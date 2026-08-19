#!/usr/bin/env python3
"""
AKT-NARYAD VERIFIER - Console Edition
Чистый консольный интерфейс для анализа актов-нарядов
"""

import sys
from pathlib import Path
import subprocess
import os
from datetime import datetime

from src.utils.app_paths import ensure_runtime_layout, get_input_dir, get_runtime_root

def print_banner():
    """Печать баннера программы"""
    banner = """
    ════════════════════════════════════════════════════════════════
          🚀  AKT-NARYAD VERIFIER v3.0 - Console Edition  🚀
          Система анализа актов-нарядов для компании Лукойл
          © Разработка и внедрение • Все права защищены
    ════════════════════════════════════════════════════════════════
    """
    print(banner)
    print(f"Запущено: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

def check_project_structure():
    """Проверка структуры проекта"""
    ensure_runtime_layout(copy_reference=True)
    project_root = Path(__file__).parent
    required = [
        get_input_dir(),
        project_root / "src" / "extractors",
    ]
    
    missing = []
    for path in required:
        if not path.exists():
            missing.append(str(path))
    
    return missing, project_root

def scan_input_files(project_root):
    """Сканирование входных файлов"""
    input_folder = get_input_dir()
    
    if not input_folder.exists():
        print("❌ Папка input не найдена!")
        return []
    
    pdf_files = list(input_folder.glob("*.pdf"))
    return pdf_files

def print_file_list(files):
    """Вывод списка файлов"""
    if files:
        print(f"📁 Найдено {len(files)} PDF файлов в папке input:")
        for i, pdf in enumerate(files, 1):
            print(f"   {i:2d}. {pdf.name}")
    else:
        print("📂 Папка input пуста или не содержит PDF файлов")
        print(f"   Поместите PDF файлы для анализа в: {get_input_dir()}")
    
    print()

def find_parser_path(parser_name, project_root):
    """Найти путь к парсеру в нескольких возможных местах"""
    possible_paths = [
        project_root / "src" / "extractors" / parser_name,
        project_root / parser_name,  # В корневой папке
    ]
    
    for path in possible_paths:
        if path.exists():
            return path
    
    return None

def run_parser(parser_name, project_root):
    """Запуск парсера"""
    script_path = find_parser_path(parser_name, project_root)
    
    if not script_path:
        print(f"❌ Ошибка: файл {parser_name} не найден!")
        print(f"   Искали в:")
        print(f"   • {project_root / 'src' / 'extractors' / parser_name}")
        print(f"   • {project_root / parser_name}")
        return False
    
    print(f"\n{'═'*60}")
    print(f"🚀 ЗАПУСК {parser_name.upper()}")
    print(f"{'═'*60}")
    print()
    
    try:
        # Запуск парсера
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=project_root,
            capture_output=False,  # Вывод сразу в консоль
            text=True
        )
        
        if result.returncode == 0:
            print(f"\n✅ {parser_name} успешно завершен!")
        else:
            print(f"\n⚠️  {parser_name} завершен с кодом {result.returncode}")
        
        return result.returncode == 0
        
    except Exception as e:
        print(f"\n❌ Ошибка при запуске {parser_name}:")
        print(f"   {str(e)}")
        return False

def show_menu():
    """Отображение главного меню"""
    print("\n" + "═"*60)
    print("ГЛАВНОЕ МЕНЮ")
    print("═"*60)
    print()
    print("Выберите действие:")
    print("  1. 🚀 Запустить Main Parser")
    print("  2. 📊 Запустить Table Parser")
    print("  3. 📈 Запустить Integral Calculator")
    print("  4. 📁 Проверить файлы")
    print("  5. 📂 Открыть папку input")
    print("  6. ❌ Выйти из программы")
    print()

def main_menu(project_root):
    """Главное меню программы"""
    while True:
        show_menu()
        
        try:
            choice = input("Введите номер действия (1-6): ").strip()
            
            if choice == "1":
                run_parser("main_parser.py", project_root)
                
            elif choice == "2":
                run_parser("table_parser.py", project_root)
                
            elif choice == "3":
                run_parser("integral.py", project_root)
                
            elif choice == "4":
                files = scan_input_files(project_root)
                print_file_list(files)
                
            elif choice == "5":
                input_folder = get_input_dir()
                if not input_folder.exists():
                    input_folder.mkdir(parents=True, exist_ok=True)
                    print(f"✓ Создана папка: {input_folder}")
                
                try:
                    if sys.platform == "win32":
                        os.startfile(input_folder)
                        print(f"📂 Открыта папку: {input_folder}")
                    elif sys.platform == "darwin":
                        subprocess.Popen(["open", input_folder])
                        print(f"📂 Открыта папку: {input_folder}")
                    else:
                        subprocess.Popen(["xdg-open", input_folder])
                        print(f"📂 Открыта папку: {input_folder}")
                except Exception as e:
                    print(f"❌ Не удалось открыть папку: {str(e)}")
                    print(f"   Папка находится по пути: {input_folder}")
                
            elif choice == "6":
                print("\n👋 Выход из программы...")
                sys.exit(0)
                
            else:
                print("❌ Неверный выбор. Пожалуйста, введите число от 1 до 6.")
                
        except KeyboardInterrupt:
            print("\n\n⚠️  Прервано пользователем")
            print("👋 Выход из программы...")
            sys.exit(0)
        except Exception as e:
            print(f"\n❌ Ошибка: {str(e)}")

def main():
    """Главная функция программы"""
    ensure_runtime_layout(copy_reference=True)
    print_banner()
    print(f"Папка данных: {get_runtime_root()}")
    
    # Проверка структуры проекта
    missing, project_root = check_project_structure()
    
    if missing:
        print("⚠️  Внимание: отсутствуют необходимые папки:")
        for path in missing:
            print(f"   • {path}")
        
        print("\nСоздать недостающие папки? (y/n): ", end="")
        response = input().strip().lower()
        
        if response == 'y' or response == 'yes' or response == 'да':
            for path in missing:
                Path(path).mkdir(parents=True, exist_ok=True)
                print(f"✓ Создано: {path}")
        else:
            print("❌ Программа не может работать без необходимых папок")
            sys.exit(1)
    
    # Сканирование файлов
    files = scan_input_files(project_root)
    print_file_list(files)
    
    # Запуск главного меню
    main_menu(project_root)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Программа прервана пользователем")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {str(e)}")
        sys.exit(1)
