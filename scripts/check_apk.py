"""Verify the fixed runner's APK contents and ABI-only packaging differences."""

import ast
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


SUPPORTED_ABIS = ("arm64-v8a", "armeabi-v7a", "x86_64")
STARTUP_TEMPLATES = ("story", "app")
BUILD_TYPES = ("debug", "release")
PROJECT_FIELDS = {
    "application_id", "display_name", "version_code", "version_name",
    "startup_template", "app_home", "input_sha256", "game_files", "python_files",
    "asset_files", "icon_sha256",
}
APP_HOME_PATTERN = r"[A-Za-z_][A-Za-z_0-9]*:[A-Za-z_][A-Za-z_0-9]*"


def _fingerprints(value, prefix=""):
    if not isinstance(value, dict):
        raise RuntimeError("Invalid supplied project file inventory")
    for name, checksum in value.items():
        if (not isinstance(name, str) or not name or "\\" in name
                or any(ord(char) < 32 for char in name)
                or not PurePosixPath(name).parts or PurePosixPath(name).is_absolute()
                or any(part in (".", "..") for part in PurePosixPath(name).parts)
                or str(PurePosixPath(name)) != name or not name.startswith(prefix)
                or not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum)):
            raise RuntimeError("Invalid supplied project file inventory")
    return value


def _project_metadata(inventory, startup_template):
    project = inventory.get("project")
    if project is None:
        return None
    if not isinstance(project, dict) or set(project) != PROJECT_FIELDS:
        raise RuntimeError("Invalid supplied project metadata")
    if (not isinstance(project["application_id"], str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z_0-9]*(?:\.[A-Za-z][A-Za-z_0-9]*)+", project["application_id"])
            or type(project["version_code"]) is not int or not 1 <= project["version_code"] <= 2100000000
            or any(not isinstance(project[key], str) or not project[key].strip()
                   or any(ord(char) < 32 for char in project[key])
                   for key in ("display_name", "version_name"))
            or project["startup_template"] != startup_template
            or (project["app_home"] is not None and (not isinstance(project["app_home"], str)
                or not re.fullmatch(APP_HOME_PATTERN, project["app_home"])))
            or inventory.get("build_type") not in BUILD_TYPES):
        raise RuntimeError("Invalid supplied project identity or startup metadata")
    game = _fingerprints(project["game_files"], "assets/x-game/")
    python = _fingerprints(project["python_files"])
    assets = _fingerprints(project["asset_files"], "flet-assets/")
    reserved = {path.stem for path in (Path(__file__).resolve().parents[1] / "runtime").glob("*.py")}
    reserved.update(sys.stdlib_module_names)
    reserved.update(("main", "renpy", "flet", "lib", "flet-assets", "third-party-notices"))
    reserved.update(name.split("/")[3].removesuffix(".py") for name in inventory["python_files"]
                    if name.startswith("lib/python3.12/site-packages/") and len(name.split("/")) > 3)
    if not game or any(PurePosixPath(name).parts[0].removesuffix(".py").removesuffix(".pyc")
                       in reserved for name in python):
        raise RuntimeError("Invalid or shadowing supplied project files")
    if project["app_home"] is not None:
        module = project["app_home"].split(":")[0]
        if module + ".py" not in python and module + "/__init__.py" not in python:
            raise RuntimeError("App home is not in the supplied Python inventory")
    icon = project["icon_sha256"]
    if icon is not None and (not isinstance(icon, str) or not re.fullmatch(r"[0-9a-f]{64}", icon)
            or assets.get("flet-assets/_renfletpy_project_icon.png") != icon):
        raise RuntimeError("Supplied project icon is not in the packaged inventory")
    try:
        data = json.dumps({key: value for key, value in project.items() if key != "input_sha256"},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except UnicodeError as error:
        raise RuntimeError("Invalid supplied project metadata encoding") from error
    if project["input_sha256"] != hashlib.sha256(data).hexdigest():
        raise RuntimeError("Changed supplied project input metadata")
    return project


def _startup_configuration(data, startup_template, project):
    try:
        statements = ast.parse(data.decode("utf-8")).body
        if statements and isinstance(statements[0], ast.Expr) and isinstance(
                statements[0].value, ast.Constant) and isinstance(statements[0].value.value, str):
            statements = statements[1:]
        values = {}
        for statement in statements:
            if (not isinstance(statement, ast.Assign) or len(statement.targets) != 1
                    or not isinstance(statement.targets[0], ast.Name)
                    or statement.targets[0].id not in ("STARTUP_TEMPLATE", "APP_HOME")
                    or statement.targets[0].id in values or not isinstance(statement.value, ast.Constant)):
                raise ValueError("Configuration must contain unique literal startup settings")
            values[statement.targets[0].id] = statement.value.value
        if (values.get("STARTUP_TEMPLATE") != startup_template
                or values.get("APP_HOME") != (project["app_home"] if project else None)
                or (project is not None and "APP_HOME" not in values)):
            raise ValueError("Configuration does not select the expected startup template/app home")
    except (SyntaxError, UnicodeError, ValueError) as error:
        raise RuntimeError("Invalid packaged startup template") from error

def check_packaged_components(apk, startup_template=None):
    inventory = json.loads(apk.read("assets/runner-capabilities.json"))
    expected = inventory["python_files"]
    assert expected, "Missing upstream package inventory"
    project = _project_metadata(inventory, startup_template or inventory.get("startup_template"))
    supplied = {} if project is None else project["python_files"] | project["asset_files"]
    if set(supplied) & set(expected):
        raise RuntimeError("Supplied project files shadow upstream components")
    expected = expected | supplied
    remaining = set(expected)
    startup_config = None
    with apk.open("assets/private.mp3") as stream, tarfile.open(fileobj=stream, mode="r|gz") as private:
        for member in private:
            if startup_template is not None and member.name == "project_config.py":
                if startup_config is not None or not member.isfile() or member.size > 4096:
                    raise RuntimeError("Invalid packaged startup configuration")
                startup_config = private.extractfile(member).read()
            if member.name in expected:
                if member.name not in remaining or not member.isfile():
                    raise RuntimeError("Duplicate or nonregular packaged file: " + member.name)
                digest = hashlib.file_digest(private.extractfile(member), "sha256").hexdigest()
                assert digest == expected[member.name], "Changed component file: " + member.name
                remaining.remove(member.name)
    assert not remaining, "Missing component files: " + ", ".join(sorted(remaining))
    if startup_template is not None:
        if startup_config is None:
            raise RuntimeError("Missing packaged startup configuration")
        if hashlib.sha256(startup_config).hexdigest() != inventory.get("project_config_sha256"):
            raise RuntimeError("Changed packaged startup configuration")
        _startup_configuration(startup_config, startup_template, project)
    android_assets = inventory.get("android_assets", {})
    if project is not None:
        android_assets = android_assets | project["game_files"]
    for name, checksum in android_assets.items():
        assert hashlib.sha256(apk.read(name)).hexdigest() == checksum, "Changed Android asset: " + name
    print("Passed: all " + str(len(inventory["python_files"])) + " upstream Python package/resource files retained in APK")
    print("Passed: all " + str(len(inventory.get("android_assets", {}))) + " RenPy common assets retained in APK")
    if project is not None:
        print("Passed: supplied project Python, assets, native game and input metadata hashes")



def inspect_apk(path, abis=SUPPORTED_ABIS, startup_template="story", *, build_type=None, project=None):
    """Require the complete extension catalog, resources and selected runtimes."""
    path = Path(path)
    if startup_template not in STARTUP_TEMPLATES:
        raise ValueError("Unsupported startup template: " + str(startup_template))
    if build_type is not None and build_type not in BUILD_TYPES:
        raise ValueError("Unsupported APK build type")
    if project is not None and (not isinstance(project, dict) or not set(project) <= PROJECT_FIELDS):
        raise ValueError("Invalid expected project metadata")
    abis = tuple(abis)
    if not abis or len(set(abis)) != len(abis) or not set(abis) <= set(SUPPORTED_ABIS):
        raise ValueError("Unsupported or duplicate runner ABI selection")
    with zipfile.ZipFile(path) as apk:
        names = set(apk.namelist())
        if len(names) != len(apk.namelist()):
            raise RuntimeError("Duplicate APK entries")
        if "assets/runner-capabilities.json" not in names:
            raise RuntimeError("Missing runner capability inventory")
        inventory = json.loads(apk.read("assets/runner-capabilities.json"))
        if inventory.get("startup_template") != startup_template:
            raise RuntimeError("APK startup template does not match expected " + startup_template)
        actual_type = inventory.get("build_type", "debug")
        if actual_type not in BUILD_TYPES or (build_type is not None and actual_type != build_type):
            raise RuntimeError("APK build type does not match expectation")
        supplied_project = _project_metadata(inventory, startup_template)
        if project is not None and (supplied_project is None or any(
                supplied_project[name] != value for name, value in project.items())):
            raise RuntimeError("APK supplied project metadata does not match expectation")
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
            libraries = ("librenpython.so", "libflutter.so") + (("libapp.so",) if actual_type == "release" else ())
            for library in libraries:
                if "lib/" + abi + "/" + library not in names:
                    raise RuntimeError("Missing runner native library: " + abi + "/" + library)
        if actual_type == "release" and "assets/flutter_assets/kernel_blob.bin" in names:
            raise RuntimeError("Release APK contains a debug Flutter Dart payload")
        if any("dart_bridge" in name or "serious_python" in name for name in names):
            raise RuntimeError("A second Python runtime was packaged")
        check_packaged_components(apk, startup_template)
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {"file": path.name, "size_bytes": path.stat().st_size, "sha256": checksum,
            "abis": list(abis), "extensions": extensions,
            "startup_template": startup_template, "source_sha": inventory["source_sha"],
            "python_files_verified": len(inventory["python_files"]),
            "android_assets_verified": len(inventory["android_assets"])}
    if "build_type" in inventory:
        report["build_type"] = actual_type
    if supplied_project is not None:
        report["project"] = supplied_project
    return report


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
