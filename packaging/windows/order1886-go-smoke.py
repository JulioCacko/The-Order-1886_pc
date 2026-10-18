"""Relocated Go/worker smoke. No game process or player state is touched."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    package = args.package.resolve()
    manifest = json.loads((package / "package-manifest.json").read_text(encoding="utf-8-sig"))
    for entry in manifest["files"]:
        path = package / entry["path"]
        if not path.resolve().is_relative_to(package):
            raise ValueError("Manifest path escapes the package.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Package hash mismatch: " + entry["path"])
    with tempfile.TemporaryDirectory(prefix="Order Go smoke ") as temporary:
        root = Path(temporary) / "Portable ç 日本語"
        shutil.copytree(package, root)
        state = Path(temporary) / "isolated player"
        environment = dict(os.environ, PATH=str(Path(os.environ["SystemRoot"]) / "System32"), PYTHONPATH="")
        for name in ("The Order 1886.exe", "Play The Order 1886.exe"):
            subprocess.run([str(root / name), "--worker-smoke", "--state-dir", str(state)],
                           cwd=temporary, env=environment, check=True, timeout=30, capture_output=True)
        worker = root / "bin/order1886-worker.exe"
        requests = [
            dict(version=1,id=1,method="settings.set",params={"values":{"vsync":False,"ui_language":"pt"}}),
            dict(version=1,id=2,method="settings.set",params={"values":{"frame_rate":90}}),
            dict(version=1,id=3,method="state.get",params={}),
        ]
        result = subprocess.run([str(worker),"--state-dir",str(state),"--installation-root",str(root)],
            input="".join(json.dumps(r)+"\n" for r in requests),text=True,encoding="utf-8",
            capture_output=True,timeout=30,check=True,cwd=temporary,env=environment)
        replies = [json.loads(line) for line in result.stdout.splitlines()]
        assert replies[0]["result"]["settings"]["vsync"] is False
        assert "error" in replies[1]
        assert replies[2]["result"]["settings"]["ui_language"] == "pt"
        assert len(replies[2]["result"]["pages"]) == 7
        assert len(replies[2]["result"]["languages"]) == 13
        assert not (state / "savedata").exists()
    print("Go portable smoke passed: manifest, both entry points, Unicode relocation, restricted PATH, worker protocol, autosave, language and rejected settings.")


if __name__ == "__main__":
    main()

