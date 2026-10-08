"""Verify the fixed runner's APK contents and ABI-only packaging differences."""

import hashlib
import json
import re
import tarfile
import zipfile
from pathlib import Path

from scripts.startup_config import STARTUP_ASSET, STARTUP_MODES, parse_startup_config

SUPPORTED_ABIS = ("arm64-v8a", "armeabi-v7a", "x86_64")

def check_packaged_components(apk):
    inventory = json.loads(apk.read("assets/runner-capabilities.json"))
    expected = inventory["python_files"]
    assert expected, "Missing upstream package inventory"
    remaining = set(expected)
    with apk.open("assets/private.mp3") as stream, tarfile.open(fileobj=stream, mode="r|gz") as private:
        for member in private:
            if member.name in expected:
                digest = hashlib.file_digest(private.extractfile(member), "sha256").hexdigest()
                assert digest == expected[member.name], "Changed component file: " + member.name
                remaining.remove(member.name)
    assert not remaining, "Missing component files: " + ", ".join(sorted(remaining))
    for name, checksum in inventory.get("android_assets", {}).items():
        assert hashlib.sha256(apk.read(name)).hexdigest() == checksum, "Changed Android asset: " + name
    print("Passed: all " + str(len(expected)) + " upstream Python package/resource files retained in APK")
    print("Passed: all " + str(len(inventory.get("android_assets", {}))) + " RenPy common assets retained in APK")



def inspect_apk(path, abis=SUPPORTED_ABIS, expected_startup_mode=None):
    """Require the complete extension catalog, resources and selected runtimes."""
    path = Path(path)
    abis = tuple(abis)
    if not abis or len(set(abis)) != len(abis) or not set(abis) <= set(SUPPORTED_ABIS):
        raise ValueError("Unsupported or duplicate runner ABI selection")
    if expected_startup_mode is not None and expected_startup_mode not in STARTUP_MODES:
        raise ValueError("Unknown expected runner startup mode")
    with zipfile.ZipFile(path) as apk:
        names = set(apk.namelist())
        if "assets/runner-capabilities.json" not in names:
            raise RuntimeError("Missing runner capability inventory")
        inventory = json.loads(apk.read("assets/runner-capabilities.json"))
        if STARTUP_ASSET not in names:
            raise RuntimeError("Missing runner startup configuration")
        startup_bytes = apk.read(STARTUP_ASSET)
        try:
            startup = parse_startup_config(startup_bytes)
        except (ValueError, TypeError) as error:
            raise RuntimeError("Invalid runner startup configuration") from error
        startup_hash = hashlib.sha256(startup_bytes).hexdigest()
        if (inventory.get("startup_mode") != startup["mode"]
                or inventory.get("startup_config_sha256") != startup_hash):
            raise RuntimeError("APK startup configuration differs from its inventory")
        if expected_startup_mode is not None and startup["mode"] != expected_startup_mode:
            raise RuntimeError("Unexpected APK startup mode: " + startup["mode"])
        expected = json.loads((Path(__file__).resolve().parents[1] /
                               "runtime/flet_extensions.json").read_text())
        extensions = inventory.get("extensions")
        if (not isinstance(extensions, list) or len(extensions) != 19
                or not all(isinstance(name, str) for name in extensions)
                or len(set(extensions)) != 19 or set(extensions) != set(expected)):
            raise RuntimeError("APK must retain all 19 fixed Flet extensions")
        if not inventory.get("android_assets"):
            raise RuntimeError("Missing RenPy common asset inventory")
        actual_abis = {name.split("/")[1] for name in names
                       if name.startswith("lib/") and not name.endswith("/")}
        if actual_abis != set(abis):
            raise RuntimeError("Unexpected APK ABIs: " + str(sorted(actual_abis)))
        for abi in abis:
            for library in ("librenpython.so", "libflutter.so"):
                if "lib/" + abi + "/" + library not in names:
                    raise RuntimeError("Missing runner native library: " + abi + "/" + library)
        if any("dart_bridge" in name or "serious_python" in name for name in names):
            raise RuntimeError("A second Python runtime was packaged")
        check_packaged_components(apk)
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"file": path.name, "size_bytes": path.stat().st_size, "sha256": checksum,
            "startup_mode": startup["mode"], "startup_config_sha256": startup_hash,
            "abis": list(abis), "extensions": extensions,
            "python_files_verified": len(inventory["python_files"]),
            "android_assets_verified": len(inventory["android_assets"])}


def compare_apk_payloads(universal, variant, abis):
    """Allow only excluded native ABI folders and regenerated APK signatures."""
    abis = set(abis)
    if not abis or not abis <= set(SUPPORTED_ABIS):
        raise ValueError("Unsupported runner ABI selection")
    excluded = set(SUPPORTED_ABIS) - abis

    def payload_entries(apk):
        return {entry.filename for entry in apk.infolist() if not entry.is_dir()
                and not re.fullmatch(r"META-INF/(?:[^/]+\.(?:RSA|DSA|EC|SF)|MANIFEST\.MF)",
                                     entry.filename, re.IGNORECASE)}

    def digest(apk, name):
        with apk.open(name) as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    with zipfile.ZipFile(universal) as full, zipfile.ZipFile(variant) as selected:
        full_entries = payload_entries(full)
        selected_entries = payload_entries(selected)
        expected = {name for name in full_entries
                    if not any(name.startswith("lib/" + abi + "/") for abi in excluded)}
        if selected_entries != expected:
            missing = sorted(expected - selected_entries)
            extra = sorted(selected_entries - expected)
            raise RuntimeError("APK variant changed payload entries: missing=" + str(missing[:8])
                               + " extra=" + str(extra[:8]))
        for name in sorted(expected):
            if digest(full, name) != digest(selected, name):
                raise RuntimeError("APK variant changed shared payload: " + name)
    print("Passed: " + str(len(expected)) +
          " shared APK payload entries have identical SHA-256 hashes")
    return len(expected)
