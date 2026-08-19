# Сборка Windows-установщика через GitHub Actions

## Цель
Получить файл:
- `AKTNaryadVerifier_installer_win_x64.exe`

без Windows-машины, используя GitHub.

## Важно
- Рекомендуется создать **приватный** репозиторий.
- Сборка не публикуется автоматически в интернет-магазины или релизы.
- Результат хранится в разделе **Actions Artifacts** вашего репозитория.

## Шаги
1. Создайте приватный репозиторий на GitHub.
2. В корне проекта выполните:
   ```bash
   git init
   git add .
   git commit -m "Prepare Windows build via GitHub Actions"
   git branch -M main
   git remote add origin https://github.com/<your_user>/<repo>.git
   git push -u origin main
   ```
3. На GitHub откройте вкладку **Actions**.
4. Выберите workflow `build-windows-installer`.
5. Нажмите **Run workflow**.
6. Дождитесь завершения сборки.
7. Откройте job и скачайте artifact `windows-installer`.
8. В архиве будут:
   - `AKTNaryadVerifier_installer_win_x64.exe`
   - файл контрольной суммы `.sha256`

## Дальше
Передайте установщик на офисный ПК и установите по инструкции:
- `packaging/OFFICE_DEPLOY_RU.md`

