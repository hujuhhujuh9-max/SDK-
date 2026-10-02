#!/usr/bin/env python3
"""Assemble the fixed Ren'Py-owned runner and build its Android debug APK."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

from prepare import BuildInputs, ROOT


def run(*command, cwd=None):
    subprocess.run([str(part) for part in command], cwd=cwd, check=True)


def copy_tree(source, target):
    shutil.copytree(source, target, dirs_exist_ok=True)


def stage_flet(inputs, work):
    target = work / "flet"
    if target.exists():
        shutil.rmtree(target)
    copy_tree(inputs.sdk_root("flet"), target)
    for patch in inputs.components["flet"].get("patches", []):
        data = inputs.branch_file("flet", patch["path"], patch["sha256"])
        subprocess.run(["patch", "--batch", "--forward", "-p1", "--directory", str(target)], input=data, check=True)
    return target


def stage_flutter(inputs, work):
    flutter = inputs.sdk_root("flutter") / "bin/flutter"
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
    run(flutter, "build", "aar", "--no-profile", "--no-release", cwd=module)
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
    shutil.copyfile(ROOT / "runtime/sdk_bridge.py", private / "sdk_bridge.py")
    notices = private / "third-party-notices"
    notices.mkdir()
    shutil.copyfile(sdk / "LICENSE.txt", notices / "RenPy-LICENSE.txt")
    shutil.copyfile(flet / "LICENSE", notices / "Flet-LICENSE.txt")
    shutil.copyfile(inputs.sdk_root("flutter") / "LICENSE", notices / "Flutter-LICENSE.txt")
    return private


def copy_assets(source, target):
    """Use the filename encoding expected by Ren'Py's Android asset loader."""
    target.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(source)
        encoded = Path(*(name if name.startswith(".") else "x-" + name for name in relative.parts))
        destination = target / encoded
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)


def stage_android(inputs, work, flet, maven):
    from jinja2 import Environment

    rapt = inputs.sdk_root("renpy-rapt")
    sdk = inputs.sdk_root("renpy")
    android = work / "android"
    if android.exists():
        shutil.rmtree(android)
    android.mkdir()
    copy_tree(rapt / "prototype/renpyandroid", android / "renpyandroid")
    copy_tree(rapt / "prototype/gradle", android / "gradle")
    for filename in ("gradlew", "gradlew.bat", "gradle.properties", "build.gradle"):
        shutil.copy2(rapt / "prototype" / filename, android / filename)
    copy_tree(ROOT / "android/app", android / "app")
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
    run(sdk / "renpy.sh", project, "compile")
    private = make_private(inputs, work, flet)
    assets = android / "app/src/main/assets"
    assets.mkdir(parents=True)
    copy_assets(project / "game", assets / "x-game")
    copy_assets(sdk / "renpy/common", assets / "x-renpy/x-common")
    archive = assets / "private.mp3"
    with tarfile.open(archive, "w:gz", format=tarfile.GNU_FORMAT) as bundle:
        for path in sorted(private.iterdir()):
            bundle.add(path, arcname=path.name)
    version = hashlib.md5(archive.read_bytes()).hexdigest()
    values = android / "app/src/main/res/values"
    values.mkdir(parents=True)
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
