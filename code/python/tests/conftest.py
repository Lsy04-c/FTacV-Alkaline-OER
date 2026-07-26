import sys
from pathlib import Path


PYTHON_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PYTHON_SRC))
