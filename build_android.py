#!/usr/bin/env python3
"""Assemble the Ren'Py-owned runner or an external project for Android."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from prepare import BuildInputs, ROOT
from scripts.check_apk import STARTUP_TEMPLATES, SUPPORTED_ABIS, compare_apk_payloads, inspect_apk


FLUTTER_CACHE_SCHEMA = 1
FLUTTER_AAR_OPTIONS = ("--no-pub", "--no-profile", "--no-release")
FLUTTER_ARTIFACT = "org/sdk/fixed_flet/flutter_debug/1.0/flutter_debug-1.0"
BUILD_TYPES = ("debug", "release")
DISABLED_ANDROID_PERMISSIONS = (
    "android.permission.CAMERA", "android.permission.RECORD_AUDIO",
    "android.permission.ACCESS_COARSE_LOCATION", "android.permission.ACCESS_FINE_LOCATION",
    "android.permission.ACCESS_BACKGROUND_LOCATION", "android.permission.FOREGROUND_SERVICE_LOCATION",
    "android.permission.FOREGROUND_SERVICE_MICROPHONE", "android.permission.CAPTURE_AUDIO_OUTPUT",
)
DISABLED_ANDROID_FEATURES = (
    "android.hardware.camera", "android.hardware.camera.autofocus", "android.hardware.microphone",
    "android.hardware.location", "android.hardware.location.gps", "android.hardware.location.network",
)
DISABLED_ANDROID_SERVICES = ("com.baseflow.geolocator.GeolocatorLocationService",)
SIGNING_ENVIRONMENT = (
    "RENFLETPY_KEYSTORE", "RENFLETPY_KEY_ALIAS", "RENFLETPY_STORE_PASSWORD", "RENFLETPY_KEY_PASSWORD",
)
PROJECT_ICON_ASSET = "_renfletpy_project_icon.png"
PROJECT_NATIVE_CONFIG = "_renfletpy_project.rpy"


def flutter_aar_options(build_type):
    if build_type not in BUILD_TYPES:
        raise ValueError("Unsupported build type: " + str(build_type))
    return FLUTTER_AAR_OPTIONS if build_type == "debug" else ("--no-pub", "--no-profile", "--no-debug")


def flutter_artifact(build_type):
    flutter_aar_options(build_type)
    return "org/sdk/fixed_flet/flutter_%s/1.0/flutter_%s-1.0" % (build_type, build_type)


def file_sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def tree_fingerprints(root):
    """Hash regular files without following cached symlinks outside the tree."""
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("Expected a regular build directory: " + str(root))
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise RuntimeError("Unexpected build input or output: " + str(path))
        if path.is_file():
            files[path.relative_to(root).as_posix()] = file_sha256(path)
    return files


def flutter_toolchain():
    sdk = Path(os.environ.get("ANDROID_HOME", os.environ.get("ANDROID_SDK_ROOT", "")))
    java = Path(os.environ["JAVA_HOME"]) / "bin/java" if os.environ.get("JAVA_HOME") else "java"
    java_version = subprocess.check_output([str(java), "-version"], stderr=subprocess.STDOUT, text=True)
    packages = {}
    for family in ("platforms", "build-tools", "ndk", "cmake"):
        for properties in sorted((sdk / family).glob("*/source.properties")):
            packages[properties.relative_to(sdk).as_posix()] = file_sha256(properties)
    # Versions select installed tools; the platform jar also affects compilation.
    packages["platforms/android-36/android.jar"] = file_sha256(sdk / "platforms/android-36/android.jar")
    return {"os": sys.platform, "arch": os.uname().machine, "java": java_version,
            "android_packages": packages}


def flutter_cache_inputs(inputs, work, build_type="debug"):
    """Identify AAR inputs after pub resolves dependencies, excluding host/story data."""
    flet = work / "flet"
    rapt = inputs.sdk_root("renpy-rapt") / "prototype"
    sources = {
        "builder": file_sha256(ROOT / "build_android.py"),
        "pubspec": file_sha256(ROOT / "flutter/pubspec.yaml"),
        "resolved_lock": file_sha256(work / "flutter/pubspec.lock"),
        "lib": tree_fingerprints(ROOT / "flutter/lib"),
        "test": tree_fingerprints(ROOT / "flutter/test"),
        "extensions": file_sha256(ROOT / "runtime/flet_extensions.json"),
        "flet": tree_fingerprints(flet / "packages/flet"),
        "flet_extensions": {project.name: tree_fingerprints(project / "src/flutter")
                            for project in sorted((flet / "sdk/python/packages").iterdir())
                            if (project / "src/flutter").is_dir()},
        "host_gradle": file_sha256(rapt / "build.gradle"),
        "gradle_wrapper": tree_fingerprints(rapt / "gradle"),
    }
    lock = ROOT / "flutter/pubspec.lock"
    sources["pinned_lock"] = file_sha256(lock) if lock.is_file() else None
    return {
        "schema_version": FLUTTER_CACHE_SCHEMA,
        "components": {name: inputs.components[name] for name in ("flutter", "flet", "renpy-rapt")},
        "sources": sources, "toolchain": flutter_toolchain(),
        "aar_options": flutter_aar_options(build_type), "abis": SUPPORTED_ABIS,
    }


def flutter_cache_fingerprint(identity):
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def flutter_repo_fingerprints(repo, build_type="debug"):
    files = tree_fingerprints(repo)
    for suffix in (".aar", ".pom"):
        name = flutter_artifact(build_type) + suffix
        if name not in files or (repo / name).stat().st_size == 0:
            raise RuntimeError("Missing Flutter " + build_type + " Maven artifact: " + name)
    return files


def reusable_flutter_repo(cache, fingerprint, build_type="debug"):
    try:
        marker = cache / "manifest.json"
        if cache.is_symlink() or marker.is_symlink():
            return False
        receipt = json.loads(marker.read_text())
        return (isinstance(receipt, dict)
                and receipt.get("schema_version") == FLUTTER_CACHE_SCHEMA
                and receipt.get("fingerprint") == fingerprint
                and receipt.get("files") == flutter_repo_fingerprints(cache / "repo", build_type))
    except (OSError, ValueError, RuntimeError):
        return False


def cache_flutter_repo(repo, cache, fingerprint, build_type="debug"):
    """Publish a complete repository and receipt together, only after a successful build."""
    files = flutter_repo_fingerprints(repo, build_type)
    with tempfile.TemporaryDirectory(prefix="flutter-aar-", dir=cache.parent) as folder:
        stage = Path(folder) / "snapshot"
        copy_tree(repo, stage / "repo")
        if flutter_repo_fingerprints(stage / "repo", build_type) != files:
            raise RuntimeError("Flutter Maven repository changed while caching")
        (stage / "manifest.json").write_text(json.dumps({
            "schema_version": FLUTTER_CACHE_SCHEMA, "fingerprint": fingerprint,
            "files": files,
        }, sort_keys=True) + "\n")
        stage.rename(cache)


def check_android_capabilities(flet, manifest=None):
    """Require the upstream client's Android declarations in our shared host."""
    android = "{http://schemas.android.com/apk/res/android}"
    source = ET.parse(flet / "client/android/app/src/main/AndroidManifest.xml").getroot()
    target = ET.parse(manifest or ROOT / "android/app/src/main/AndroidManifest.xml").getroot()
    require_android_declarations(source, target)
    application = target.find("application")
    if application.get(android + "enableOnBackInvokedCallback") != "true":
        raise RuntimeError("Android back-gesture support must remain enabled")
    if any(node.get(android + "name") == "io.flutter.embedding.android.EnableImpeller"
           and node.get(android + "value") == "false" for node in application.findall("meta-data")):
        raise RuntimeError("The shared host must retain Flutter's renderer selection")


def require_android_declarations(source, target):
    android = "{http://schemas.android.com/apk/res/android}"
    tools = "{http://schemas.android.com/tools}"
    for tag, blocked in (("uses-permission", DISABLED_ANDROID_PERMISSIONS),
                         ("uses-feature", DISABLED_ANDROID_FEATURES),
                         ("application/service", DISABLED_ANDROID_SERVICES)):
        declared = {node.get(android + "name"): node for node in target.findall(tag)}
        for name in blocked:
            if name not in declared or declared[name].get(tools + "node") != "remove":
                description = "Phone camera access" if "camera" in name.lower() else "Disabled Android capability"
                raise RuntimeError(description + " must be removed: " + name)
    for tag in ("uses-permission", "uses-feature"):
        declared = {node.get(android + "name") or node.get(android + "glEsVersion"): node
                    for node in target.findall(tag)}
        for node in source.findall(tag):
            name = node.get(android + "name") or node.get(android + "glEsVersion")
            if name in DISABLED_ANDROID_PERMISSIONS + DISABLED_ANDROID_FEATURES:
                continue
            if name not in declared:
                raise RuntimeError("Missing upstream Android declaration: " + name)
            if node.get(android + "required") == "false" and declared[name].get(android + "required") != "false":
                raise RuntimeError("Optional upstream Android feature became required: " + name)
    for node in source.findall("application/provider"):
        name = node.get(android + "name")
        if not any(other.get(android + "name") == name for other in target.findall("application/provider")):
            raise RuntimeError("Missing upstream Android provider: " + name)
    if source.find("application").get(android + "allowBackup") == "true" and target.find("application").get(android + "allowBackup") != "true":
        raise RuntimeError("Upstream Android backup support was disabled")


def package_fingerprints(source, prefix, exclude=()):
    """Record upstream package bytes, including data files and type stubs."""
    return {str(Path(prefix) / path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
            and path.relative_to(source).parts[0] not in exclude}


def check_extension_registry(modules, registry=None):
    """Require each packaged extension to be initialized once by the host."""
    if registry is None:
        registry = (ROOT / "flutter/lib/extensions.dart").read_text()
    registered = re.findall(r"\b(flet_[a-z_0-9]+)\.Extension\(\)", registry)
    if set(registered) != modules or len(registered) != len(modules):
        raise RuntimeError("The host Flet extension registry differs from the fixed catalog")


def extension_projects(flet):
    """Require the fixed catalog to cover the pinned full Flet client's extensions."""
    names = json.loads((ROOT / "runtime/flet_extensions.json").read_text())
    modules = {name.replace("-", "_") for name in names}
    upstream = set(re.findall(r"package:(flet_[a-z_0-9]+)/",
                             (flet / "client/lib/main.dart").read_text()))
    if len(modules) != len(names) or modules != upstream:
        raise RuntimeError("The fixed Flet extension catalog differs from the pinned client")
    check_extension_registry(modules)
    projects = []
    for name in names:
        project = flet / "sdk/python/packages" / name
        module = name.replace("-", "_")
        if not (project / "src" / module / "__init__.py").is_file():
            raise RuntimeError("Missing Flet Python extension: " + name)
        if not (project / "src/flutter" / module / "pubspec.yaml").is_file():
            raise RuntimeError("Missing Flet Dart extension: " + name)
        projects.append((project, module))
    return projects


def copy_flet_extensions(flet, site, notices):
    for project, module in extension_projects(flet):
        copy_tree(project / "src" / module, site / module)
        shutil.copyfile(project / "LICENSE", notices / (project.name + "-LICENSE.txt"))
        metadata = tomllib.loads((project / "pyproject.toml").read_text())["project"]
        info = site / (module + "-" + metadata["version"] + ".dist-info")
        info.mkdir(exist_ok=True)
        (info / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: " + metadata["name"] +
            "\nVersion: " + metadata["version"] + "\n")
        shutil.copyfile(project / "LICENSE", info / "LICENSE")


def apply_component_patches(inputs, component, target, strip=1):
    for patch in inputs.components[component].get("patches", []):
        data = inputs.branch_file(component, patch["path"], patch["sha256"])
        subprocess.run(["patch", "--batch", "--forward", "-p" + str(strip), "--directory", str(target)], input=data, check=True)


def run(*command, cwd=None):
    subprocess.run([str(part) for part in command], cwd=cwd, check=True)


def copy_tree(source, target):
    shutil.copytree(source, target, dirs_exist_ok=True)


def stage_flet(inputs, work):
    target = work / "flet"
    if target.exists():
        shutil.rmtree(target)
    copy_tree(inputs.sdk_root("flet"), target)
    apply_component_patches(inputs, "flet", target)
    extension_projects(target)
    check_android_capabilities(target)
    return target


def stage_flutter(inputs, work, force_build=False, build_type="debug"):
    aar_options = flutter_aar_options(build_type)
    flutter = inputs.sdk_root("flutter") / "bin/flutter"
    # Native plugin setup (including Rive) invokes dart from Gradle.
    os.environ["PATH"] = os.pathsep.join([
        str(flutter.parent), str(flutter.parent / "cache/dart-sdk/bin"),
        os.environ.get("PATH", ""),
    ])
    module = work / "flutter"
    # Recreate generated paths and remove deleted sources even when an AAR is reused.
    if module.exists():
        shutil.rmtree(module)
    run(flutter, "create", "--template", "module", "--project-name", "fixed_flet", "--org", "org.sdk", module)
    shutil.copyfile(ROOT / "flutter/pubspec.yaml", module / "pubspec.yaml")
    shutil.rmtree(module / "lib")
    copy_tree(ROOT / "flutter/lib", module / "lib")
    tests = module / "test"
    if tests.exists():
        shutil.rmtree(tests)
    copy_tree(ROOT / "flutter/test", tests)
    lock = ROOT / "flutter/pubspec.lock"
    if lock.is_file():
        shutil.copyfile(lock, module / "pubspec.lock")
    run(flutter, "pub", "get", cwd=module)
    run(flutter, "analyze", "--no-pub", "lib", "test", cwd=module)
    run(flutter, "test", "--no-pub", cwd=module)
    # Use the same AGP as the native host. Flutter's generated AGP 9 build
    # disables built-in Kotlin, while file_picker 11 skips KGP on AGP 9.
    host_gradle = (inputs.sdk_root("renpy-rapt") / "prototype/build.gradle").read_text()
    agp = re.search(r'id "com.android.library" version "([^"]+)"', host_gradle).group(1)
    settings = module / ".android/settings.gradle"
    content, count = re.subn(r'(id "com.android.library" version ")[^"]+(" apply false)',
                             lambda match: match[1] + agp + match[2], settings.read_text())
    if count != 1:
        raise RuntimeError("Expected one generated Android library plugin declaration")
    settings.write_text(content)
    print("Flutter AAR uses the RAPT Android Gradle plugin " + agp, flush=True)
    identity = flutter_cache_inputs(inputs, work, build_type)
    fingerprint = flutter_cache_fingerprint(identity)
    cache = inputs.cache / ("flutter-aar" if build_type == "debug" else "flutter-aar-release")
    if not force_build and reusable_flutter_repo(cache, fingerprint, build_type):
        print("Reusing verified Flutter " + build_type + " AAR: " + fingerprint, flush=True)
        return cache / "repo"
    # Invalidate before building so a failed/forced rebuild cannot leave a valid receipt.
    if cache.is_symlink() or cache.is_file():
        cache.unlink()
    elif cache.exists():
        shutil.rmtree(cache)
    print("Building Flutter " + build_type + " AAR (cache miss or forced rebuild): " + fingerprint, flush=True)
    run(flutter, "build", "aar", *aar_options, cwd=module)
    # Gradle can install SDK packages and write into plugin source directories.
    # Keep the original source snapshot and record only the final toolchain.
    toolchain = flutter_toolchain()
    previous_packages = identity["toolchain"]["android_packages"]
    changed_packages = sorted(name for name, checksum in toolchain["android_packages"].items()
                              if previous_packages.get(name) != checksum)
    if changed_packages:
        print("Flutter build changed Android SDK packages: " + ", ".join(changed_packages), flush=True)
    identity["toolchain"] = toolchain
    fingerprint = flutter_cache_fingerprint(identity)
    cache_flutter_repo(module / "build/host/outputs/repo", cache, fingerprint, build_type)
    print("Cached verified Flutter " + build_type + " AAR: " + fingerprint, flush=True)
    return cache / "repo"


def stage_runtime(target, startup_template, project=None):
    """Use the same build-selected configuration for compilation and packaging."""
    if startup_template not in STARTUP_TEMPLATES:
        raise ValueError("Unsupported startup template: " + str(startup_template))
    target.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / "runtime").glob("*.py"):
        shutil.copyfile(source, target / source.name)
    if project is not None:
        copy_tree(project.python_dir, target)
    (target / "project_config.py").write_text(
        '\"\"\"Build-selected entry point, kept outside Ren\'Py save state.\"\"\"\n\n'
        'STARTUP_TEMPLATE = "' + startup_template + '"\n'
        'APP_HOME = ' + repr(project.app_home if project is not None else None) + '\n')


def project_input_inventory(project):
    metadata = {
        "application_id": project.application_id, "display_name": project.display_name,
        "version_code": project.version_code, "version_name": project.version_name,
        "startup_template": project.startup_template, "app_home": project.app_home,
        "game_files": {str(Path("assets/x-game") / encoded_asset_path(Path(name))): digest
                       for name, digest in tree_fingerprints(project.game_dir).items()},
        "python_files": tree_fingerprints(project.python_dir),
        "asset_files": {"flet-assets/" + name: digest
                        for name, digest in tree_fingerprints(project.assets_dir).items()},
        "icon_sha256": file_sha256(project.icon) if project.icon is not None else None,
    }
    if project.icon is not None:
        if (project.assets_dir / PROJECT_ICON_ASSET).exists():
            raise ValueError("Project assets contain reserved icon input: " + PROJECT_ICON_ASSET)
        metadata["asset_files"]["flet-assets/" + PROJECT_ICON_ASSET] = metadata["icon_sha256"]
    metadata["input_sha256"] = hashlib.sha256(json.dumps(
        metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    return metadata


def make_private(inputs, work, flet, startup_template="story", project=None):
    sdk = inputs.sdk_root("renpy")
    private = work / "private"
    if private.exists():
        shutil.rmtree(private)
    private.mkdir()
    shutil.copyfile(sdk / "renpy.py", private / "main.py")
    shutil.copytree(sdk / "renpy", private / "renpy", ignore=shutil.ignore_patterns("common", "__pycache__"))
    copy_tree(sdk / "lib/python3.12", private / "lib/python3.12")
    site = private / "lib/python3.12/site-packages"
    run(sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--target", site,
        "--only-binary=:all:", "-r", ROOT / "runtime/requirements.txt")
    # MsgPack supplies a Python implementation; desktop native extensions must
    # never be shipped into the Android interpreter.
    for pattern in ("*.so", "*.pyd", "*.dll"):
        for native in site.rglob(pattern):
            native.unlink()
    copy_tree(flet / "sdk/python/packages/flet/src/flet", site / "flet")
    stage_runtime(private, startup_template, project)
    shutil.copyfile(ROOT / "runtime/flet_extensions.json", private / "flet_extensions.json")
    copy_tree(project.assets_dir if project is not None else ROOT / "assets", private / "flet-assets")
    if project is not None and project.icon is not None:
        shutil.copyfile(project.icon, private / "flet-assets" / PROJECT_ICON_ASSET)
    # A real tone and moving picture let the device checks prove output,
    # rather than accepting a duration from a silent/static fixture.
    if not (private / "flet-assets/runner.wav").exists():
        run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=16000:duration=30", "-c:a", "pcm_s16le",
            private / "flet-assets/runner.wav")
    if not (private / "flet-assets/runner.mp4").exists():
        run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
            "testsrc2=size=160x90:rate=12:duration=30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            private / "flet-assets/runner.mp4")
    shutil.copyfile(ROOT / "LICENSE", private / "PROJECT-NOTICE.txt")
    notices = private / "third-party-notices"
    notices.mkdir()
    shutil.copyfile(sdk / "LICENSE.txt", notices / "RenPy-LICENSE.txt")
    shutil.copyfile(flet / "LICENSE", notices / "Flet-LICENSE.txt")
    shutil.copyfile(inputs.sdk_root("flutter") / "LICENSE", notices / "Flutter-LICENSE.txt")
    copy_flet_extensions(flet, site, notices)
    for notice in inputs.components["renpy-rapt"].get("notices", []):
        (notices / Path(notice["path"]).name).write_bytes(
            inputs.branch_file("renpy-rapt", notice["path"], notice["sha256"]))
    return private


def encoded_asset_path(relative):
    return Path(*(name if name.startswith(".") else "x-" + name for name in relative.parts))


def copy_assets(source, target):
    """Use the filename encoding expected by Ren'Py's Android asset loader."""
    target.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(source)
        encoded = encoded_asset_path(relative)
        destination = target / encoded
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)


def configure_android_project(android, project):
    properties = {
        "runnerApplicationId": project.application_id, "runnerVersionCode": str(project.version_code),
        "runnerVersionName": project.version_name, "runnerLabel": "@string/renfletpy_project_name",
        "runnerScheme": project.application_id.replace(".", "-").replace("_", "-").lower(),
    }
    with (android / "gradle.properties").open("a") as stream:
        stream.write("\n" + "\n".join(name + "=" + value for name, value in properties.items()) + "\n")
    values = android / "app/src/main/res/values"
    values.mkdir(parents=True, exist_ok=True)
    resources = ET.Element("resources")
    label = ET.SubElement(resources, "string", name="renfletpy_project_name", translatable="false", formatted="false")
    label.text = '"' + project.display_name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    ET.ElementTree(resources).write(values / "project.xml", encoding="utf-8", xml_declaration=True)
    if project.icon is not None:
        drawable = android / "app/src/main/res/drawable"
        drawable.mkdir(parents=True, exist_ok=True)
        (drawable / "runner_icon.xml").unlink(missing_ok=True)
        shutil.copyfile(project.icon, drawable / "runner_icon.png")


def stage_android(inputs, work, flet, maven, startup_template="story", *, project=None, build_type="debug"):
    from jinja2 import Environment

    rapt = inputs.sdk_root("renpy-rapt")
    sdk = inputs.sdk_root("renpy")
    template = Environment().from_string((rapt / "templates/app-AndroidManifest.xml").read_text())
    baseline = ET.fromstring(template.render(config={
        "store": "none", "package": "${applicationId}",
        "orientation": "fullUser", "permissions": [],
    }, manifest_extra=""))
    require_android_declarations(baseline, ET.parse(ROOT / "android/app/src/main/AndroidManifest.xml").getroot())
    android = work / "android"
    if android.exists():
        shutil.rmtree(android)
    android.mkdir()
    copy_tree(rapt / "prototype/renpyandroid", android / "renpyandroid")
    apply_component_patches(inputs, "renpy-rapt", android, strip=2)
    copy_tree(rapt / "prototype/gradle", android / "gradle")
    for filename in ("gradlew", "gradlew.bat", "gradle.properties", "build.gradle"):
        shutil.copy2(rapt / "prototype" / filename, android / filename)
    copy_tree(ROOT / "android/app", android / "app")
    if project is not None:
        configure_android_project(android, project)
    shutil.copyfile(ROOT / "android/renpyandroid-dependencies.gradle", android / "renpyandroid-dependencies.gradle")
    with (android / "renpyandroid/build.gradle").open("a") as gradle:
        gradle.write('\napply from: rootProject.file("renpyandroid-dependencies.gradle")\n')
    constants = Environment().from_string((rapt / "templates/Constants.java").read_text()).render(
        config={"store": "none"}, big_bundle=False)
    (android / "renpyandroid/src/main/java/org/renpy/android/Constants.java").write_text(constants)
    sdk_path = Path(os.environ.get("ANDROID_HOME", os.environ.get("ANDROID_SDK_ROOT", "")))
    if not (sdk_path / "platforms/android-36/android.jar").is_file():
        raise RuntimeError("ANDROID_HOME must contain platforms;android-36")
    (android / "local.properties").write_text("sdk.dir=" + str(sdk_path.resolve()) + "\n")
    settings = '''pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven { url = uri(%s) }
        maven { url = uri("https://storage.googleapis.com/download.flutter.io") }
    }
}
rootProject.name = "fixed-runner"
include ':renpyandroid', ':app'
''' % json.dumps(str(maven))
    (android / "settings.gradle").write_text(settings)
    native_project = work / ("renpy-project" if startup_template == "story" else "renpy-project-app")
    # Recreate generated inputs so removed sources and compiled files cannot linger.
    if native_project.exists():
        shutil.rmtree(native_project)
    copy_tree(project.game_dir if project is not None else ROOT / "game", native_project / "game")
    stage_runtime(native_project, startup_template, project)
    if project is not None:
        native_config = native_project / "game" / PROJECT_NATIVE_CONFIG
        if native_config.exists():
            raise ValueError("Project game contains reserved native configuration: " + PROJECT_NATIVE_CONFIG)
        native_config.write_text(
            "init 999 python:\n"
            "    config.name = " + repr(project.display_name) + "\n"
            "    config.version = " + repr(project.version_name) + "\n"
            "    config.save_directory = " + repr(project.application_id) + "\n")
    run(sdk / "renpy.sh", native_project, "compile")
    private = make_private(inputs, work, flet, startup_template, project)
    assets = android / "app/src/main/assets"
    assets.mkdir(parents=True)
    inventory = {
        "startup_template": startup_template,
        "project_config_sha256": file_sha256(private / "project_config.py"),
        "source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "extensions": json.loads((ROOT / "runtime/flet_extensions.json").read_text()),
        "python_files": (
            package_fingerprints(sdk / "renpy", "renpy", exclude=("common",)) |
            package_fingerprints(flet / "sdk/python/packages/flet/src/flet",
                                 "lib/python3.12/site-packages/flet") |
            {name: checksum for project, module in extension_projects(flet)
             for name, checksum in package_fingerprints(
                 project / "src" / module, "lib/python3.12/site-packages/" + module).items()}
        ),
        "android_assets": {
            str(Path("assets/x-renpy/x-common") / encoded_asset_path(Path(name))): checksum
            for name, checksum in package_fingerprints(sdk / "renpy/common", "").items()
        }
    }
    if project is not None or build_type != "debug":
        inventory["build_type"] = build_type
    if project is not None:
        inventory["project"] = project_input_inventory(project)
    (assets / "runner-capabilities.json").write_text(json.dumps(inventory) + "\n")
    copy_assets(native_project / "game", assets / "x-game")
    copy_assets(sdk / "renpy/common", assets / "x-renpy/x-common")
    archive = assets / "private.mp3"
    with tarfile.open(archive, "w:gz", format=tarfile.GNU_FORMAT) as bundle:
        for path in sorted(private.iterdir()):
            bundle.add(path, arcname=path.name)
    version = hashlib.md5(archive.read_bytes()).hexdigest()
    values = android / "app/src/main/res/values"
    values.mkdir(parents=True, exist_ok=True)
    resources = ET.Element("resources")
    ET.SubElement(resources, "string", name="private_version", translatable="false").text = version
    ET.ElementTree(resources).write(values / "strings.xml", encoding="utf-8", xml_declaration=True)
    return android


def release_signing(environment=None):
    environment = os.environ if environment is None else environment
    values = [environment.get(name) for name in SIGNING_ENVIRONMENT]
    if not any(values):
        return False
    if not all(values):
        raise ValueError("Release signing requires all four RENFLETPY signing environment values")
    keystore = Path(values[0]).expanduser().resolve()
    if not keystore.is_file():
        raise ValueError("RENFLETPY_KEYSTORE must name an existing keystore file")
    environment["RENFLETPY_KEYSTORE"] = str(keystore)
    return True


def artifact_names(startup_template, build_type="debug", project=None):
    if project is not None:
        slug = project.application_id.replace(".", "-")
        return ("runner-" + slug + "-" + build_type,
                "apk-builds-" + slug + "-" + build_type + ".json")
    app = "-app" if startup_template == "app" else ""
    prefix = "runner" + app + "-" + build_type
    receipt = "apk-builds" + app + ("" if build_type == "debug" else "-release") + ".json"
    return prefix, receipt


def check_merged_android_capabilities(apk, aapt):
    permissions = subprocess.check_output([str(aapt), "dump", "permissions", str(apk)], text=True)
    declared = set(re.findall(r"^uses-permission[^\n]*\bname=['\"]([^'\"]+)['\"]", permissions, re.MULTILINE))
    blocked = declared.intersection(DISABLED_ANDROID_PERMISSIONS)
    if blocked:
        raise RuntimeError("The merged APK requests disabled Android permissions: " + ", ".join(sorted(blocked)))
    manifest = subprocess.check_output([str(aapt), "dump", "xmltree", str(apk), "AndroidManifest.xml"], text=True)
    names = set(re.findall(r"\bname\([^)]*\)=\"([^\"]+)\"", manifest))
    if names.intersection(DISABLED_ANDROID_SERVICES):
        raise RuntimeError("The merged APK retains a disabled Android location service")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".android-build")
    parser.add_argument("--archives", type=Path)
    parser.add_argument("--startup-template", choices=STARTUP_TEMPLATES,
                        help="Select story-first startup (default) or the optional app starter.")
    parser.add_argument("--project", type=Path, help="Build an external renfletpy.json project.")
    parser.add_argument("--build-type", choices=BUILD_TYPES, default="debug")
    parser.add_argument("--force-flutter-build", action="store_true",
                        help="Rebuild the selected Flutter AAR instead of reusing verified output.")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12 to match Ren'Py's packaged interpreter and dependencies")
    project = None
    if args.project is not None:
        from project import load_project
        try:
            project = load_project(args.project)
        except (OSError, ValueError) as error:
            parser.error("Invalid project: " + str(error))
        if args.startup_template is not None and args.startup_template != project.startup_template:
            parser.error("The startup template must match the external project's configuration")
    startup_template = project.startup_template if project is not None else (args.startup_template or "story")
    try:
        signed = release_signing() if args.build_type == "release" else False
    except (OSError, ValueError) as error:
        parser.error("Invalid release signing: " + str(error))
    inputs = BuildInputs(args.cache_dir, args.archives)
    for component in inputs.components:
        inputs.setup(component)
    work = inputs.cache / "integration"
    work.mkdir(parents=True, exist_ok=True)
    flet = stage_flet(inputs, work)
    run(sys.executable, ROOT / "scripts/check_flet_bridge.py", flet)
    if args.build_type == "debug":
        maven = stage_flutter(inputs, work, force_build=args.force_flutter_build)
    else:
        maven = stage_flutter(inputs, work, force_build=args.force_flutter_build, build_type=args.build_type)
    if project is None and args.build_type == "debug":
        android = stage_android(inputs, work, flet, maven, startup_template)
    else:
        android = stage_android(inputs, work, flet, maven, startup_template,
                                project=project, build_type=args.build_type)
    output = inputs.cache / "outputs"
    output.mkdir(exist_ok=True)
    built = android / "app/build/outputs/apk" / args.build_type / (
        "app-release-unsigned.apk" if args.build_type == "release" and not signed else "app-" + args.build_type + ".apk")
    reports = []
    prefix, receipt = artifact_names(startup_template, args.build_type, project)
    for filename, abis, options in (
            (prefix + ".apk", SUPPORTED_ABIS, ()),
            (prefix + "-x86_64.apk", ("x86_64",), ("-PrunnerAbi=x86_64",))):
        run(android / "gradlew", "--no-daemon", *options,
            ":app:assemble" + args.build_type.title(), cwd=android)
        if not built.is_file():
            raise RuntimeError("Gradle did not produce the runner APK")
        apk = output / filename
        shutil.copyfile(built, apk)
        aapt = Path(os.environ["ANDROID_HOME"]) / "build-tools/36.0.0/aapt"
        check_merged_android_capabilities(apk, aapt)
        if signed:
            run(aapt.parent / "apksigner", "verify", "--verbose", apk)
        inspection = {} if project is None and args.build_type == "debug" else {"build_type": args.build_type}
        if project is not None:
            inspection["project"] = project_input_inventory(project)
        report = inspect_apk(apk, abis, startup_template=startup_template, **inspection)
        reports.append(report)
        print("Built verified APK: " + json.dumps(report, sort_keys=True), flush=True)
    shared_entries = compare_apk_payloads(output / (prefix + ".apk"),
                                         output / (prefix + "-x86_64.apk"), ("x86_64",))
    result = {
        "startup_template": startup_template, "source_sha": reports[0]["source_sha"],
        "apks": reports, "identical_shared_entries": shared_entries,
    }
    if project is not None or args.build_type == "release":
        signing = "debug" if args.build_type == "debug" else ("signed" if signed else "unsigned")
        result.update(build_type=args.build_type, signing=signing)
    if project is not None:
        result["project"] = project_input_inventory(project)
    (output / receipt).write_text(json.dumps(result, indent=2) + "\n")
    if args.build_type == "release" and not signed:
        print("Release APKs are unsigned; supply the signing environment values to build installable APKs.", flush=True)


if __name__ == "__main__":
    main()
