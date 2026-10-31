"""Command-line entry point; the implementation lives in scripts/order1886_ui_extract.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from order1886_ui_extract import main  # noqa: E402

if __name__ == "__main__":
    main()
