#!/usr/bin/env python3
"""Inspect a built kext as data; do not invoke its executable or a loader."""
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def inspect(bundle, output):
    bundle = bundle.resolve()
    output = output.resolve()
    assert ROOT in bundle.parents and ROOT in output.parents
    output.mkdir(parents=True, exist_ok=True)
    plist_path = bundle / "Contents/Info.plist"
    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["CFBundleIdentifier"] == "com.qhuyduong.AMDMicrophone"
    personality = plist["IOKitPersonalities"]["AMDMicrophone"]
    assert personality["IOPCIMatch"].lower() == "0x15e21022"
    assert personality["IOPCIClassMatch"].lower() == "0x04800000"
    expected = plistlib.loads((ROOT / "upstream/AMDMicrophone/Info.plist").read_bytes())
    assert plist["OSBundleLibraries"] == expected["OSBundleLibraries"], "Dipendenze inattese"
    binary = bundle / "Contents/MacOS" / plist["CFBundleExecutable"]
    assert binary.is_file()
    commands = {
        "file": ["/usr/bin/file", str(binary)],
        "architectures": ["/usr/bin/lipo", "-archs", str(binary)],
        "macho-header": ["/usr/bin/otool", "-hv", str(binary)],
        "macho-load-commands": ["/usr/bin/otool", "-l", str(binary)],
        "macho-libraries": ["/usr/bin/otool", "-L", str(binary)],
        "undefined-symbols": ["/usr/bin/nm", "-u", str(binary)],
        "codesign-description": ["/usr/bin/codesign", "-d", "--verbose=4", str(bundle)],
        "codesign-verification": ["/usr/bin/codesign", "--verify", "--strict", "--verbose=4", str(bundle)],
        "plist-lint": ["/usr/bin/plutil", "-lint", str(plist_path)],
    }
    results = {}
    for label, command in commands.items():
        p = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        (output / (label + ".txt")).write_text(p.stdout)
        results[label] = {"exit_code": p.returncode, "output": p.stdout}
        if not label.startswith("codesign-"):
            assert p.returncode == 0, label
    assert results["architectures"]["output"].split() == ["x86_64"], "Architettura inattesa"
    assert "KEXTBUNDLE" in results["macho-header"]["output"], "Tipo Mach-O inatteso"
    hashes = []
    for path in sorted(bundle.rglob("*")):
        assert not path.is_symlink(), "Symlink inatteso nel candidato"
        if path.is_file():
            hashes.append({"path": str(path.relative_to(bundle)),
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "size": path.stat().st_size})
    description = results["codesign-description"]["output"].lower()
    signing = "unsigned" if "not signed" in description else "inspect-codesign-report"
    result = {
        "status": "statically-inspected-not-loaded",
        "bundle_identifier": plist["CFBundleIdentifier"],
        "bundle_version": plist.get("CFBundleVersion"),
        "architecture": "x86_64",
        "dependencies": plist["OSBundleLibraries"],
        "signing": signing,
        "signing_is_not_apple_trust_validation": True,
        "files": hashes,
    }
    (output / "candidate-metadata.json").write_text(json.dumps(result, indent=2) + "\n")
    (output / "Info.plist").write_bytes(plist_path.read_bytes())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Uso: inspect_candidate.py BUNDLE DIRECTORY_REPORT")
    inspect(Path(sys.argv[1]), Path(sys.argv[2]))
