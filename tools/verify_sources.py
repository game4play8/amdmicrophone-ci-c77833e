#!/usr/bin/env python3
"""Verify the two pinned Git checkouts. Never load or install a kext."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
PINS = {
    "upstream": "c77833e1eef3b22df02f4b1d8f87e15e4e02f0c9",
    "upstream/MacKernelSDK": "c41d877b64e7fd916bd271390bcdf30f7deb7b7a",
}


def git(repo, *args):
    return subprocess.check_output(["/usr/bin/git", "-C", str(repo), *args])


def verify():
    entries = []
    counts = {}
    for relative, expected in PINS.items():
        repo = ROOT / relative
        assert git(repo, "rev-parse", "HEAD").decode().strip() == expected, relative
        assert not git(repo, "status", "--porcelain=v1", "--untracked-files=all").strip(), (
            "Checkout modificato: " + relative
        )
        subprocess.run(["/usr/bin/git", "-C", str(repo), "fsck", "--full"], check=True)
        count = 0
        for record in git(repo, "ls-tree", "-r", "-z", "HEAD").split(b"\0"):
            if not record:
                continue
            header, filename = record.split(b"\t", 1)
            mode, kind, object_id = header.decode().split()
            name = os.fsdecode(filename)
            if kind == "commit":
                assert relative == "upstream" and name == "MacKernelSDK"
                assert object_id == PINS["upstream/MacKernelSDK"]
                continue
            assert kind == "blob", (relative, name, kind)
            path = repo / name
            data = os.fsencode(os.readlink(path)) if mode == "120000" else path.read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            assert blob == object_id, "Git blob non corrispondente: " + str(path)
            entries.append({
                "path": relative + "/" + name,
                "mode": mode,
                "size": len(data),
                "git_blob_sha1": blob,
                "sha256": hashlib.sha256(data).hexdigest(),
            })
            count += 1
        counts[relative] = count
    assert git(ROOT / "upstream", "config", "-f", ".gitmodules", "--get",
               "submodule.MacKernelSDK.url").decode().strip() == (
                   "https://github.com/acidanthera/MacKernelSDK"
               )
    return {"status": "verified", "pins": PINS, "counts": counts, "files": entries}


if __name__ == "__main__":
    result = verify()
    if len(sys.argv) == 2:
        destination = Path(sys.argv[1]).resolve()
        assert ROOT in destination.parents, "Output fuori dal workspace isolato"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "pins", "counts")}, indent=2))
