"""Preserve licenses for the frozen Python runtime, bootloader and UI libraries."""
from importlib import metadata
from pathlib import Path
import shutil
import sys


def collect(destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    base = Path(sys.base_prefix)
    core = list(base.glob("LICENSE*"))
    if not core:
        raise RuntimeError("The build Python installation has no license notice")
    for source in core:
        shutil.copy2(source, destination / ("CPython-" + source.name))
    for name in ("pillow", "pyinstaller", "pyinstaller-hooks-contrib"):
        distribution = metadata.distribution(name)
        count = 0
        for file in distribution.files or ():
            parts = file.parts
            notice = any(part.lower() == "licenses" for part in parts) or file.name.lower().startswith(("license", "licence", "copying", "notice"))
            if not notice or not any(part.endswith(".dist-info") for part in parts):
                continue
            relative = Path(*parts[next(i for i, part in enumerate(parts) if part.endswith(".dist-info")) + 1:])
            target = destination / name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(distribution.locate_file(file), target)
            count += 1
        if not count:
            raise RuntimeError(f"No license notice found for {name}")
    for source in (base / "tcl").rglob("license.terms"):
        target = destination / source.relative_to(base)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


if __name__ == "__main__":
    collect(Path(sys.argv[1]))
