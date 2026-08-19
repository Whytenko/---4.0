#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import hashlib
from pathlib import Path


def find_iscc() -> Path | None:
    candidates = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if sys.platform != "win32":
        print("This script can be run only on Windows.")
        return 1

    project_root = Path(__file__).resolve().parents[2]
    dist_dir = project_root / "dist" / "AKTNaryadVerifier"
    iss_path = project_root / "packaging" / "windows" / "AKTNaryadVerifier.iss"

    if not dist_dir.exists():
        print(f"Build folder not found: {dist_dir}")
        print("Run first: python packaging/build_portable.py")
        return 1

    if not iss_path.exists():
        print(f"Installer script not found: {iss_path}")
        return 1

    iscc = find_iscc()
    if not iscc:
        print("ISCC.exe not found. Install Inno Setup 6.")
        return 1

    cmd = [str(iscc), str(iss_path)]
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=project_root, check=True)
    release_dir = project_root / "release"
    installer = release_dir / "AKTNaryadVerifier_installer_win_x64.exe"
    if installer.exists():
        checksum = sha256sum(installer)
        checksum_path = release_dir / f"{installer.name}.sha256"
        checksum_path.write_text(f"{checksum}  {installer.name}\n", encoding="utf-8")
        print(f"Installer: {installer}")
        print(f"SHA-256 file: {checksum_path}")
    else:
        print("Installer built in release folder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
