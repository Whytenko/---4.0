# Distribution Guide

## Goal
Build separate offline packages for Windows, macOS and Linux without admin rights for end users.

## Runtime behavior
- User data folder is created automatically on first run:
  - Windows: `%LOCALAPPDATA%\\AktNaryadVerifier`
  - macOS: `~/Library/Application Support/AktNaryadVerifier`
  - Linux: `~/.local/share/AktNaryadVerifier`
- Main folders:
  - `input` (user adds PDF files here)
  - `reference` (copied from bundled app on first run)
  - `ml_cache`, `logs`, `output`

## Build locally (current OS)
1. Install build dependencies:
   - `python -m pip install -r requirements-build.txt`
2. Build:
   - `python packaging/build_portable.py`
3. Result:
   - `release/AKTNaryadVerifier_<os>_<arch>.zip`

## Windows installer (no admin)
Prerequisite: Inno Setup 6 installed on build machine.

1. Build portable first:
   - `python packaging/build_portable.py`
2. Build installer:
   - `python packaging/windows/build_installer.py`
3. Result:
   - `release/AKTNaryadVerifier_installer_win_x64.exe`

Installer properties:
- user-level install path: `%LOCALAPPDATA%\\Programs\\AKTNaryadVerifier`
- no admin rights required
- creates Start Menu shortcut and Desktop shortcut automatically

## Cross-platform strategy
Use native build per OS (recommended):
- Build Windows package on Windows runner/machine
- Build macOS package on macOS runner/machine
- Build Linux package on Linux runner/machine

Do **not** rely on cross-compiling Windows from macOS for production artifacts.

## Security hardening
- Ship checksums for every release archive (SHA-256).
- Sign binaries:
  - Windows: Authenticode code signing certificate.
  - macOS: Apple Developer ID signing + notarization.
- Keep portable package user-level only (no admin required).

## OCR note
The app uses Tesseract for OCR.
- Windows CI builds install Tesseract and bundle it into the installer automatically.
- Preferred packaging layout for manual builds: put binary in `tesseract/bin/tesseract` (or `tesseract/bin/tesseract.exe`) near app files.
