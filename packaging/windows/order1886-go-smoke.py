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
        if (package / "The Order 1886 Legacy.exe").exists():
            raise ValueError("A Go-only package must not ship the previous launcher.")
        if manifest.get("update_abi") != "order1886-update-2":
            raise ValueError("Package does not advertise the update recovery ABI.")
        for name in ("The Order 1886.exe", "Play The Order 1886.exe"):
            subprocess.run([str(root / name), "--worker-smoke", "--state-dir", str(state)],
                           cwd=temporary, env=environment, check=True, timeout=30, capture_output=True)
        # The helper runs before any window exists; on a clean package it must find
        # nothing to recover and must not leave a journal behind.
        recovery = subprocess.run([str(root / "The Order 1886.exe"), "--update-helper",
                                   "--update-action", "recover", "--update-installation", str(root),
                                   "--no-relaunch"],
                                  cwd=temporary, env=environment, timeout=30, capture_output=True)
        if recovery.returncode:
            raise ValueError("Update helper refused a clean package: " + recovery.stderr.decode("utf-8", "replace"))
        if (root / ".order1886-update" / "journal.json").exists():
            raise ValueError("Update helper wrote a journal for a clean package.")
        # order1886.py resolves its imports from the shipped scripts/ directory at runtime, so a
        # missing module only shows up on Play. Ask the backend for help: it must reach argument
        # parsing and exit 0 rather than dying on an import.
        backend = subprocess.run([str(root / "bin/order1886-worker.exe"), "--run-backend", "--help"],
                                 cwd=temporary, env=environment, timeout=60, capture_output=True)
        if backend.returncode != 0:
            raise ValueError("Packaged backend cannot import its modules: "
                             + (backend.stderr or backend.stdout).decode("utf-8", "replace")[-600:])
        worker = root / "bin/order1886-worker.exe"
        requests = [
            dict(version=1,id=1,method="settings.set",params={"values":{"vsync":False,"ui_language":"pt"}}),
            dict(version=1,id=2,method="settings.set",params={"values":{"frame_rate":120}}),  # 30, 60, 90 and 0 are offered
            dict(version=1,id=3,method="state.get",params={}),
            dict(version=1,id=4,method="updates.preflight",params={}),
            dict(version=1,id=5,method="patches.list",params={}),
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
        assert replies[3]["result"]["ready"] is True
        rows = replies[4]["result"]["recipes"]
        assert len(rows) >= 2 and all(row["id"] and row["title"] for row in rows)
        # Applicability is decided against the selected game; with none it must be a reason.
        assert all(row["applicable"] is False and row["reason"] for row in rows)
        assert not (state / "savedata").exists()
    print("Go portable smoke passed: manifest, both entry points, update ABI and clean helper, Unicode relocation, restricted PATH, worker protocol, update preflight, autosave, language and rejected settings.")


if __name__ == "__main__":
    main()

