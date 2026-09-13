import os
import shutil
import subprocess
import sys
import tempfile
import ctypes

# WindowsコンソールのUnicode出力対応
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def get_short_path(path):
    try:
        buf = ctypes.create_unicode_buffer(2048)
        ret = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 2048)
        if ret > 0:
            return buf.value
    except Exception as e:
        print("Short path error:", e)
    return path

def build_exe():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_dist_dir = os.path.join(project_root, "dist")
    
    # テンポラリディレクトリ（ASCII/絵文字を含まない場所）を作成してビルド
    temp_dir = tempfile.mkdtemp(prefix="ada_build_")
    temp_work = os.path.join(temp_dir, "build")
    temp_dist = os.path.join(temp_dir, "dist")
    temp_spec = temp_dir

    main_py = os.path.join(project_root, "main.py")
    short_main_py = get_short_path(main_py)
    
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--hide-console=hide-early",
        "--name=ArchitecturalDrawingAnalyzer",
        f"--distpath={temp_dist}",
        f"--workpath={temp_work}",
        f"--specpath={temp_spec}",
        short_main_py
    ]

    
    print("Running PyInstaller build command:", " ".join(cmd))
    print(f"Building in temporary directory: {temp_dir}")
    
    try:
        result = subprocess.run(cmd, cwd=temp_dir)
        if result.returncode == 0:
            src_app = os.path.join(temp_dist, "ArchitecturalDrawingAnalyzer")
            dest_app = os.path.join(target_dist_dir, "ArchitecturalDrawingAnalyzer")
            
            if os.path.exists(dest_app):
                shutil.rmtree(dest_app)
            os.makedirs(target_dist_dir, exist_ok=True)
            shutil.copytree(src_app, dest_app)
            
            exe_path = os.path.join(dest_app, "ArchitecturalDrawingAnalyzer.exe")
            print("Build succeeded! EXE path:", exe_path)
        else:
            print("Build failed with return code:", result.returncode)
            sys.exit(result.returncode)
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass

if __name__ == "__main__":
    build_exe()

