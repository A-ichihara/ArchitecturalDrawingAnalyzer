"""Build the Windows application with PyInstaller.

This script must not modify the Python installation or site-packages used to
run it. Build artifacts are created in a temporary directory and copied to
the project's dist/ directory only after a successful build.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import tempfile


def get_short_path(path: str) -> str:
    """Return a Windows short path when available (helps with Unicode paths)."""
    if sys.platform != "win32":
        return path
    try:
        buf = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf))
        if 0 < length < len(buf):
            return buf.value
    except Exception:
        pass
    return path


def build_exe() -> None:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_dist_dir = os.path.join(project_root, "dist")
    temp_dir = tempfile.mkdtemp(prefix="ada_build_")
    temp_work = os.path.join(temp_dir, "build")
    temp_dist = os.path.join(temp_dir, "dist")
    main_py = get_short_path(os.path.join(project_root, "main.py"))

    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--hide-console=hide-early",
        "--name=ArchitecturalDrawingAnalyzer",
        f"--distpath={temp_dist}",
        f"--workpath={temp_work}",
        f"--specpath={temp_dir}",
        main_py,
    ]

    try:
        print("Running PyInstaller build command:", " ".join(cmd))
        print("Building in temporary directory:", temp_dir)
        result = subprocess.run(cmd, cwd=temp_dir, check=False)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd)

        built_app = os.path.join(temp_dist, "ArchitecturalDrawingAnalyzer")
        exe_path = os.path.join(built_app, "ArchitecturalDrawingAnalyzer.exe")
        if not os.path.isfile(exe_path):
            raise FileNotFoundError(
                f"PyInstaller reported success but the executable was not found: {exe_path}"
            )

        os.makedirs(target_dist_dir, exist_ok=True)
        dest_app = os.path.join(target_dist_dir, "ArchitecturalDrawingAnalyzer")
        staging_app = os.path.join(target_dist_dir, "ArchitecturalDrawingAnalyzer.new")
        backup_app = os.path.join(target_dist_dir, "ArchitecturalDrawingAnalyzer.old")

        for path in (staging_app, backup_app):
            if os.path.exists(path):
                shutil.rmtree(path)

        shutil.copytree(built_app, staging_app)
        if os.path.exists(dest_app):
            os.replace(dest_app, backup_app)
        try:
            os.replace(staging_app, dest_app)
        except Exception:
            if os.path.exists(backup_app) and not os.path.exists(dest_app):
                os.replace(backup_app, dest_app)
            raise
        if os.path.exists(backup_app):
            shutil.rmtree(backup_app)

        print(
            "Build succeeded! EXE path:",
            os.path.join(dest_app, "ArchitecturalDrawingAnalyzer.exe"),
        )
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception as exc:
            print(f"Warning: could not remove temporary build directory {temp_dir}: {exc}")


if __name__ == "__main__":
    build_exe()
