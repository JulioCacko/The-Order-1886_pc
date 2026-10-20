"""Preserve licenses for the frozen Python runtime, bootloader and UI libraries."""
from importlib import metadata
from pathlib import Path
import shutil
import sys
import sysconfig


def cpython_licenses():
    """Every place a CPython installation keeps its license, newest layout first.

    The interpreter shipped by actions/setup-python does not keep a LICENSE in its prefix, so a single
    `base_prefix` lookup failed on Linux after the same code had worked on Windows. Debian keeps it as
    /usr/share/doc/python3*/copyright instead.
    """
    candidates = [Path(sys.base_prefix), Path(sys.prefix)]
    stdlib = sysconfig.get_path('stdlib')
    if stdlib:
        candidates.append(Path(stdlib).parent)
    found = []
    for base in candidates:
        if not base.is_dir():
            continue
        found.extend(sorted(base.glob('LICENSE*')) + sorted(base.glob('LICENCE*')))
    if not found:
        found.extend(sorted(Path('/usr/share/doc').glob('python3*/copyright')))
    return found


def collect(destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    core = cpython_licenses()
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
