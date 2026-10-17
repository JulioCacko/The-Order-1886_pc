"""Convert the user's supplied official game emblem to a multi-size Windows ICO."""
from pathlib import Path
import sys
from PIL import Image


def create_icon(destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).resolve().parents[2] / "launcher/order1886/app-icon.png"
    with Image.open(source) as emblem:
        image = emblem.convert("RGBA").resize((256, 256), Image.Resampling.LANCZOS)
    image.save(destination / "order1886.ico", sizes=[(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)])
    (destination / "ARTWORK.txt").write_text(
        "Official The Order: 1886 emblem supplied by the user on 2026-10-17.\n"
        "ICO format conversion of launcher/order1886/app-icon.png by "
        "packaging/windows/order1886_icon.py. Source PNG is preserved unchanged.\n"
        "Artwork and trademarks retain the rights of their respective owners.\n", encoding="utf-8")


if __name__ == "__main__":
    create_icon(Path(sys.argv[1]))
