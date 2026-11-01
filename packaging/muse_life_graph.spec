# PyInstaller spec for the downloadable Windows app (one folder, a console window that says where it runs).
#   pyinstaller packaging/muse_life_graph.spec --noconfirm      (run from a clean checkout; see packaging/build.ps1)
# Only code, the web pages and the prompts go in: no data/, no .env, no faces (scripts/check_bundle.py verifies).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "mlg" / "web" / "static"), "mlg/web/static"),
           (str(ROOT / "mlg" / "prompts"), "mlg/prompts"),
           (str(ROOT / "LICENSE"), ".")] + collect_data_files("certifi"),
    # scipy (pulled in by imagehash) imports parts of itself lazily that the analysis cannot see
    hiddenimports=collect_submodules("uvicorn") + collect_submodules("mlg") + ["tkinter", "tkinter.filedialog"]
    + collect_submodules("scipy._external") + collect_submodules("scipy.fft") + collect_submodules("scipy.fftpack"),
    excludes=["torch", "transformers", "pytest", "matplotlib", "IPython", "notebook", "mlg.studio.gpu_worker"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MuseLifeGraph", console=True,
          icon=str(ROOT / "packaging" / "icon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="MuseLifeGraph")
