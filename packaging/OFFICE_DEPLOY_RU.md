# Руководство по установке (Windows, без прав администратора)

## Комплект поставки
1. `AKTNaryadVerifier_installer_win_x64.exe`
2. `AKTNaryadVerifier_installer_win_x64.exe.sha256` (контроль целостности)
3. Настоящее руководство.

## Пошаговая установка
1. Скопируйте установщик на локальный диск рабочего ПК.
2. Запустите `AKTNaryadVerifier_installer_win_x64.exe`.
3. Выполните установку с параметрами по умолчанию.
4. После завершения установки используйте ярлык `AKTNaryadVerifier` на рабочем столе.
5. Запустите программу.
6. Поместите PDF акты в каталог:
   - `%LOCALAPPDATA%\AktNaryadVerifier\input`
7. Выполните анализ документов в интерфейсе программы.

## Каталоги приложения
- `%LOCALAPPDATA%\AktNaryadVerifier\input` — входящие PDF
- `%LOCALAPPDATA%\AktNaryadVerifier\reference` — справочники
- `%LOCALAPPDATA%\AktNaryadVerifier\ml_cache` — кэш ML
- `%LOCALAPPDATA%\AktNaryadVerifier\logs` — журналы
- `%LOCALAPPDATA%\AktNaryadVerifier\output` — выходные данные

## Проверка целостности файла (рекомендуется)
Команда в `cmd`:
```bat
certutil -hashfile AKTNaryadVerifier_installer_win_x64.exe SHA256
```
Сравните хеш с содержимым файла `.sha256`.

## Примечание по OCR
В Windows-сборке OCR-движок Tesseract включается в установщик автоматически.  
Дополнительная установка Tesseract на целевом ПК обычно не требуется.

## Диагностика после установки
Проверка окружения и базовый smoke-тест:
```bat
"%LOCALAPPDATA%\Programs\AKTNaryadVerifier\AKTNaryadVerifier.exe" --self-check
"%LOCALAPPDATA%\Programs\AKTNaryadVerifier\AKTNaryadVerifier.exe" --smoke-test
```

Результаты самопроверки сохраняются в:
- `%LOCALAPPDATA%\AktNaryadVerifier\logs\self_check_latest.txt`
- `%LOCALAPPDATA%\AktNaryadVerifier\logs\self_check_latest.json`
