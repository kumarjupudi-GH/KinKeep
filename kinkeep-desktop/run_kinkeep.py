"""Entry point used by PyInstaller and by `python run_kinkeep.py`."""
import sys
from kinkeep_desktop.app import main

if __name__ == "__main__":
    sys.exit(main())
