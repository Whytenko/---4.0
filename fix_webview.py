"""
Обходной путь для установки webview без компиляции
"""
import sys
import subprocess
import os

def install_webview_workaround():
    print("=" * 60)
    print("УСТАНОВКА WEBVIEW (ОБХОДНОЙ ПУТЬ)")
    print("=" * 60)
    
    # Проверяем версию Python
    version = sys.version_info
    print(f"Python версия: {version.major}.{version.minor}.{version.micro}")
    
    # Скачиваем предварительно собранный wheel
    base_url = "https://files.pythonhosted.org/packages"
    
    if version.major == 3 and version.minor == 10:
        url = f"{base_url}/cp310/p/pywebview/pywebview-3.6.2-cp310-cp310-win_amd64.whl"
    elif version.major == 3 and version.minor == 9:
        url = f"{base_url}/cp39/p/pywebview/pywebview-3.6.2-cp39-cp39-win_amd64.whl"
    elif version.major == 3 and version.minor == 11:
        url = f"{base_url}/cp311/p/pywebview/pywebview-3.6.2-cp311-cp311-win_amd64.whl"
    elif version.major == 3 and version.minor == 12:
        url = f"{base_url}/cp312/p/pywebview/pywebview-3.6.2-cp312-cp312-win_amd64.whl"
    else:
        print(f"⚠️  Неизвестная версия Python: {version.major}.{version.minor}")
        print("Попробуем установить pywebview напрямую...")
        url = "pywebview"
    
    print(f"Скачиваем: {url}")
    
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", url])
        print("✅ PyWebView установлен успешно!")
    except:
        print("⚠️  Пробуем другой способ...")
        try:
            # Пробуем установить без зависимостей
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pywebview==3.6.2", "--no-deps"])
            print("✅ PyWebView установлен без зависимостей")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return False
    
    print("\n" + "=" * 60)
    print("Создаем обертку для совместимости...")
    print("=" * 60)
    
    # Создаем файл webview.py для совместимости
    wrapper_code = '''
# webview.py - обертка для совместимости
import sys

try:
    # Пробуем импортировать как pywebview
    from pywebview import *
    from pywebview import __version__
    
    # Делаем доступными все функции под старым именем
    sys.modules['webview'] = sys.modules['pywebview']
    
except ImportError as e:
    print("Ошибка импорта webview:", e)
    print("Установите: pip install pywebview")
    raise
'''
    
    with open('webview.py', 'w', encoding='utf-8') as f:
        f.write(wrapper_code)
    
    print("✅ Файл webview.py создан")
    
    # Устанавливаем остальные зависимости
    print("\n" + "=" * 60)
    print("Устанавливаем остальные библиотеки...")
    print("=" * 60)
    
    dependencies = ["pdfplumber", "pandas", "openpyxl", "pytz"]
    for dep in dependencies:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", dep])
            print(f"✅ {dep} установлен")
        except:
            print(f"⚠️  Не удалось установить {dep}")
    
    print("\n" + "=" * 60)
    print("ПРОВЕРКА УСТАНОВКИ")
    print("=" * 60)
    
    try:
        # Тестируем импорт
        import webview
        import pdfplumber
        import pandas
        
        print("✅ Все библиотеки установлены успешно!")
        print(f"Версия webview: {webview.__version__}")
        
        print("\n" + "=" * 60)
        print("ЗАПУСК ПРОГРАММЫ")
        print("=" * 60)
        print("Запустите: python interface.py")
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = install_webview_workaround()
    if success:
        input("\nНажмите Enter для выхода...")
    else:
        print("\n⚠️  Установка завершилась с ошибками")
        input("Нажмите Enter для выхода...")