#!/usr/bin/env python3
"""Assemble the fixed Ren'Py-owned runner and build its Android debug APK."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

from prepare import BuildInputs, ROOT


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
    for tag in ("uses-permission", "uses-feature"):
        declared = {node.get(android + "name") or node.get(android + "glEsVersion"): node
                    for node in target.findall(tag)}
        for node in source.findall(tag):
            name = node.get(android + "name") or node.get(android + "glEsVersion")
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


def stage_flutter(inputs, work):
    flutter = inputs.sdk_root("flutter") / "bin/flutter"
    # Native plugin setup (including Rive) invokes dart from Gradle.
    os.environ["PATH"] = os.pathsep.join([
        str(flutter.parent), str(flutter.parent / "cache/dart-sdk/bin"),
        os.environ.get("PATH", ""),
    ])
    module = work / "flutter"
    if not (module / ".android").is_dir():
        run(flutter, "create", "--template", "module", "--project-name", "fixed_flet", "--org", "org.sdk", module)
    shutil.copyfile(ROOT / "flutter/pubspec.yaml", module / "pubspec.yaml")
    copy_tree(ROOT / "flutter/lib", module / "lib")
    lock = ROOT / "flutter/pubspec.lock"
    if lock.is_file():
        shutil.copyfile(lock, module / "pubspec.lock")
    run(flutter, "pub", "get", cwd=module)
    run(flutter, "analyze", "--no-pub", "lib", cwd=module)
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
    run(flutter, "build", "aar", "--no-pub", "--no-profile", "--no-release", cwd=module)
    return module / "build/host/outputs/repo"


def make_private(inputs, work, flet):
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
    for source in (ROOT / "runtime").glob("*.py"):
        shutil.copyfile(source, private / source.name)
    shutil.copyfile(ROOT / "runtime/flet_extensions.json", private / "flet_extensions.json")
    copy_tree(ROOT / "assets", private / "flet-assets")
    with wave.open(str(private / "flet-assets/runner.wav"), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 4000)
    run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
        "color=c=blue:size=64x64:rate=10", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
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


def stage_android(inputs, work, flet, maven):
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
    project = work / "renpy-project"
    copy_tree(ROOT / "game", project / "game")
    shutil.copyfile(ROOT / "runtime/sdk_bridge.py", project / "sdk_bridge.py")
    run(sdk / "renpy.sh", project, "compile")
    private = make_private(inputs, work, flet)
    assets = android / "app/src/main/assets"
    assets.mkdir(parents=True)
    (assets / "runner-capabilities.json").write_text(json.dumps({
        "extensions": json.loads((ROOT / "runtime/flet_extensions.json").read_text()),
        "python_files": dict(
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
    }) + "\n")
    copy_assets(project / "game", assets / "x-game")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".android-build")
    parser.add_argument("--archives", type=Path)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12 to match Ren'Py's packaged interpreter and dependencies")
    inputs = BuildInputs(args.cache_dir, args.archives)
    for component in inputs.components:
        inputs.setup(component)
    work = inputs.cache / "integration"
    work.mkdir(parents=True, exist_ok=True)
    flet = stage_flet(inputs, work)
    run(sys.executable, ROOT / "scripts/check_flet_bridge.py", flet)
    maven = stage_flutter(inputs, work)
    android = stage_android(inputs, work, flet, maven)
    run(android / "gradlew", "--no-daemon", ":app:assembleDebug", cwd=android)
    apk = android / "app/build/outputs/apk/debug/app-debug.apk"
    if not apk.is_file():
        raise RuntimeError("Gradle did not produce the runner APK")
    output = inputs.cache / "outputs"
    output.mkdir(exist_ok=True)
    shutil.copyfile(apk, output / "runner-debug.apk")
    print("Built " + str(output / "runner-debug.apk"), flush=True)


if __name__ == "__main__":
    main()
