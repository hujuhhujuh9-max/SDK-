"""Verify the fixed runner's APK contents and ABI-only packaging differences."""

import ast
import hashlib
import json
import re
import tarfile
import zipfile
from pathlib import Path


SUPPORTED_ABIS = ("arm64-v8a", "armeabi-v7a", "x86_64")
STARTUP_TEMPLATES = ("story", "app")

def check_packaged_components(apk, startup_template=None):
    inventory = json.loads(apk.read("assets/runner-capabilities.json"))
    expected = inventory["python_files"]
    assert expected, "Missing upstream package inventory"
    remaining = set(expected)
    startup_config = None
    with apk.open("assets/private.mp3") as stream, tarfile.open(fileobj=stream, mode="r|gz") as private:
        for member in private:
            if startup_template is not None and member.name == "project_config.py":
                if startup_config is not None or not member.isfile() or member.size > 4096:
                    raise RuntimeError("Invalid packaged startup configuration")
                startup_config = private.extractfile(member).read()
            if member.name in expected:
                digest = hashlib.file_digest(private.extractfile(member), "sha256").hexdigest()
                assert digest == expected[member.name], "Changed component file: " + member.name
                remaining.remove(member.name)
    assert not remaining, "Missing component files: " + ", ".join(sorted(remaining))
    if startup_template is not None:
        if startup_config is None:
            raise RuntimeError("Missing packaged startup configuration")
        if hashlib.sha256(startup_config).hexdigest() != inventory.get("project_config_sha256"):
            raise RuntimeError("Changed packaged startup configuration")
        try:
            statements = ast.parse(startup_config.decode("utf-8")).body
            if statements and isinstance(statements[0], ast.Expr) and isinstance(
                    statements[0].value, ast.Constant) and isinstance(statements[0].value.value, str):
                statements = statements[1:]
            if (len(statements) != 1 or not isinstance(statements[0], ast.Assign)
                    or len(statements[0].targets) != 1
                    or not isinstance(statements[0].targets[0], ast.Name)
                    or statements[0].targets[0].id != "STARTUP_TEMPLATE"
                    or not isinstance(statements[0].value, ast.Constant)
                    or statements[0].value.value != startup_template):
                raise ValueError("Configuration does not select the expected startup template")
        except (SyntaxError, UnicodeError, ValueError) as error:
            raise RuntimeError("Invalid packaged startup template") from error
    for name, checksum in inventory.get("android_assets", {}).items():
        assert hashlib.sha256(apk.read(name)).hexdigest() == checksum, "Changed Android asset: " + name
    print("Passed: all " + str(len(expected)) + " upstream Python package/resource files retained in APK")
    print("Passed: all " + str(len(inventory.get("android_assets", {}))) + " RenPy common assets retained in APK")



def inspect_apk(path, abis=SUPPORTED_ABIS, startup_template="story"):
    """Require the complete extension catalog, resources and selected runtimes."""
    path = Path(path)
    if startup_template not in STARTUP_TEMPLATES:
        raise ValueError("Unsupported startup template: " + str(startup_template))
    abis = tuple(abis)
    if not abis or len(set(abis)) != len(abis) or not set(abis) <= set(SUPPORTED_ABIS):
        raise ValueError("Unsupported or duplicate runner ABI selection")
    with zipfile.ZipFile(path) as apk:
        names = set(apk.namelist())
        if "assets/runner-capabilities.json" not in names:
            raise RuntimeError("Missing runner capability inventory")
        inventory = json.loads(apk.read("assets/runner-capabilities.json"))
        if inventory.get("startup_template") != startup_template:
            raise RuntimeError("APK startup template does not match expected " + startup_template)
        if not isinstance(inventory.get("source_sha"), str) or not re.fullmatch(
                r"[0-9a-f]{40}", inventory["source_sha"]):
            raise RuntimeError("Missing or invalid APK source revision")
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
        check_packaged_components(apk, startup_template)
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"file": path.name, "size_bytes": path.stat().st_size, "sha256": checksum,
            "abis": list(abis), "extensions": extensions,
            "startup_template": startup_template, "source_sha": inventory["source_sha"],
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
