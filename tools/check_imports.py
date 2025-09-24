from pathlib import Path
import importlib
import sys
import traceback

root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


def try_import(name):
    print(f"Testing import: {name}")
    try:
        m = importlib.import_module(name)
        importlib.reload(m)
        print(f"{name} OK")
    except Exception:
        print(f"{name} ERR")
        traceback.print_exc()


if __name__ == '__main__':
    try_import('onboarding')
    try_import('sitebuilder.ui.main_window')
    try_import('MainApp')
