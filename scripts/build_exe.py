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
        "--exclude-module=pathlib",
        "--exclude-module=matplotlib",
        "--exclude-module=numpy",
        "--exclude-module=scipy",
        "--exclude-module=pandas",
        "--exclude-module=PIL",
        "--exclude-module=tkinter",
        "--exclude-module=PyQt5",
        "--exclude-module=PyQt6",
        "--name=ArchitecturalDrawingAnalyzer",
        f"--distpath={temp_dist}",
        f"--workpath={temp_work}",
        f"--specpath={temp_spec}",
        short_main_py
    ]

    
    # C:\Users\aichi\anaconda3\lib\site-packages 配下の不要な旧 pathlib 関連の一次退避
    site_packages = r"C:\Users\aichi\anaconda3\lib\site-packages"
    moved_items = []

    if os.path.exists(site_packages):
        for fname in os.listdir(site_packages):
            if "pathlib" in fname.lower() and not fname.endswith(".bak_ada"):
                src = os.path.join(site_packages, fname)
                dst = src + ".bak_ada"
                try:
                    os.rename(src, dst)
                    moved_items.append((src, dst))
                except Exception as e:
                    print(f"Failed to move {fname}:", e)
        if moved_items:
            print(f"Temporarily moved {len(moved_items)} obsolete pathlib items.")

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
        for src, dst in moved_items:
            if os.path.exists(dst):
                try:
                    os.rename(dst, src)
                except Exception:
                    pass
        if moved_items:
            print("Restored obsolete pathlib items.")
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass



if __name__ == "__main__":
    build_exe()

