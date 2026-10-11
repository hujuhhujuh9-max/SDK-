"""Validate and stage project-owned paired Flet packages without executing them.

The pinned FletExtension and @flet.control interfaces are the runtime API. This
module supplies build inputs and generated registration, not another widget API.
"""

import hashlib
import json
import keyword
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml


PACKAGE_NAME = r"[a-z][a-z0-9_]*"
EXTENSION_FIELDS = {"name", "python_package", "dart_package", "dart_entrypoint",
                    "dart_extension", "control_types", "service_types", "license",
                    "python_dependencies"}
REQUIRED_EXTENSION_FIELDS = {"name", "python_package", "dart_package", "license"}


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError("pubspec keys must be unique strings: " + str(key))
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                             _unique_mapping)


def _load_pubspec(path):
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueLoader)
        # Exclude YAML-only values, dates and recursive aliases from receipts.
        json.dumps(value, allow_nan=False)
    except (UnicodeError, yaml.YAMLError, TypeError, OverflowError, RecursionError) as error:
        raise ValueError("Invalid project extension pubspec.yaml: " + str(path)) from error
    if not isinstance(value, dict):
        raise ValueError("Project extension pubspec.yaml must be an object.")
    return value


def _relative_file(package, field, value, *, directory=False):
    from project import _source_path
    return _source_path(package, field, value, directory=directory)


def _asset_files(package, pubspec):
    """Resolve package assets to files, preserving Flutter's package asset keys."""
    flutter = pubspec.get("flutter", {})
    if not isinstance(flutter, dict):
        raise ValueError("Project extension flutter configuration must be an object.")
    assets = flutter.get("assets", [])
    fonts = flutter.get("fonts", [])
    if not isinstance(assets, list) or not isinstance(fonts, list):
        raise ValueError("Project extension assets/fonts must be lists.")
    files = set()
    for asset in assets:
        if not isinstance(asset, str):
            raise ValueError("Project extension assets support file/directory strings only.")
        candidate = package / asset
        path = _relative_file(package, "extension asset", asset, directory=candidate.is_dir())
        if path.is_dir():
            # Flutter includes only direct files for a directory entry. Resolution
            # variants are included automatically beneath a declared image.
            files.update(child for child in path.iterdir() if child.is_file())
        else:
            files.add(path)
        for variant in path.parent.glob("*x/" + path.name):
            if variant.is_file():
                files.add(variant)
    for family in fonts:
        if not isinstance(family, dict) or not isinstance(family.get("fonts"), list):
            raise ValueError("Project extension fonts need a family and fonts list.")
        for font in family["fonts"]:
            if not isinstance(font, dict):
                raise ValueError("Project extension font must be an asset object.")
            files.add(_relative_file(package, "extension font", font.get("asset")))
    return tuple(sorted(path.relative_to(package).as_posix() for path in files))


def _dependencies(pubspec, package, selected, field):
    dependencies = pubspec.get(field, {})
    if not isinstance(dependencies, dict):
        raise ValueError("Project extension " + field + " must be an object.")
    for name, source in dependencies.items():
        if not re.fullmatch(PACKAGE_NAME, name):
            raise ValueError("Invalid Dart dependency name: " + name)
        if isinstance(source, str) and source.strip():
            continue
        if isinstance(source, dict) and source == {"sdk": "flutter"}:
            continue
        if isinstance(source, dict) and set(source) == {"path"}:
            target = selected.get(name)
            relative = source["path"]
            if (target is not None and isinstance(relative, str) and relative
                    and not Path(relative).is_absolute() and "\\" not in relative
                    and (package / relative).resolve() == target):
                continue
            raise ValueError("Local Dart dependencies must select another declared paired extension: " + name)
        raise ValueError("Unsupported Dart dependency " + name
                         + ": use hosted version constraints, Flutter SDK, or a declared paired package.")
    return dependencies


@dataclass(frozen=True)
class ProjectExtension:
    name: str
    python_package: Path
    dart_package: Path
    dart_entrypoint: str
    dart_extension: str
    control_types: tuple[str, ...]
    service_types: tuple[str, ...]
    license: Path
    pubspec: dict
    assets: tuple[str, ...]


def validate_extensions(value, root, sources, reserved):
    from project import _source_path, _source_tree
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError("extensions must be a list of at most 64 paired packages.")
    selected = {}
    records = []
    all_paths = list(sources.values())
    for config in value:
        if (not isinstance(config, dict) or set(config) - EXTENSION_FIELDS
                or REQUIRED_EXTENSION_FIELDS - set(config)):
            raise ValueError("Invalid project extension fields; require name, python_package, dart_package and license.")
        name = config["name"]
        if (not isinstance(name, str) or not re.fullmatch(PACKAGE_NAME, name)
                or keyword.iskeyword(name) or name in reserved or name in selected
                or name in ("flutter", "flutter_test", "fixed_flet", "dart")):
            raise ValueError("Project extension name duplicates or shadows a package: " + str(name))
        if config.get("python_dependencies", []) != []:
            raise ValueError("Project Python dependencies are not installed from pip. Bundle pure Python source; native Python dependencies are unsupported.")
        paths = {field: _source_path(root, "extension " + field, config[field])
                 for field in ("python_package", "dart_package")}
        for path in paths.values():
            if any(path.is_relative_to(other) or other.is_relative_to(path) for other in all_paths):
                raise ValueError("Project extension source directories must not overlap application or extension sources.")
            _source_tree(path)
            all_paths.append(path)
        if not (paths["python_package"] / "__init__.py").is_file():
            raise ValueError("Project extension python_package needs __init__.py: " + name)
        pubspec_file = paths["dart_package"] / "pubspec.yaml"
        if not pubspec_file.is_file():
            raise ValueError("Project extension dart_package needs pubspec.yaml: " + name)
        pubspec = _load_pubspec(pubspec_file)
        if pubspec.get("name") != name:
            raise ValueError("Dart pubspec name must match paired extension name: " + name)
        if any(field in pubspec for field in ("dependency_overrides", "workspace", "resolution")):
            raise ValueError("Project extensions cannot override SDK dependencies or use pub workspaces: " + name)
        entrypoint = config.get("dart_entrypoint", name + ".dart")
        entry = _relative_file(paths["dart_package"] / "lib", "dart_entrypoint", entrypoint)
        if entry.suffix != ".dart":
            raise ValueError("dart_entrypoint must be a Dart file under lib.")
        constructor = config.get("dart_extension", "Extension")
        if not isinstance(constructor, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", constructor):
            raise ValueError("dart_extension must name a zero-argument FletExtension class.")
        types = {}
        for field in ("control_types", "service_types"):
            names = config.get(field, [])
            if (not isinstance(names, list) or len(names) != len(set(str(item) for item in names))
                    or any(not isinstance(item, str) or not re.fullmatch(
                        re.escape(name) + r"\.[A-Za-z][A-Za-z_0-9]*", item) for item in names)):
                raise ValueError(field + " must contain unique names prefixed with " + name + ".")
            types[field] = tuple(names)
        if not types["control_types"] and not types["service_types"]:
            raise ValueError("Project extension must declare at least one control or service type.")
        if set(types["control_types"]) & set(types["service_types"]):
            raise ValueError("A project extension wire type cannot be both a control and service.")
        license_file = _source_path(root, "extension license", config["license"], directory=False)
        if not license_file.read_bytes().strip():
            raise ValueError("Project extension license must not be empty: " + name)
        selected[name] = paths["dart_package"]
        records.append(ProjectExtension(name=name, dart_entrypoint=entrypoint,
                       dart_extension=constructor, license=license_file, pubspec=pubspec,
                       assets=_asset_files(paths["dart_package"], pubspec), **paths, **types))
    for extension in records:
        for field in ("dependencies", "dev_dependencies"):
            _dependencies(extension.pubspec, extension.dart_package, selected, field)
    return tuple(records)


def _files(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def extension_inventory(extension):
    return {
        "name": extension.name,
        "dart_entrypoint": extension.dart_entrypoint,
        "dart_extension": extension.dart_extension,
        "control_types": list(extension.control_types),
        "service_types": list(extension.service_types),
        "python_files": {extension.name + "/" + path: digest
                         for path, digest in _files(extension.python_package).items()},
        "dart_files": _files(extension.dart_package),
        "assets": {"assets/flutter_assets/packages/" + extension.name + "/" + path:
                   hashlib.sha256((extension.dart_package / path).read_bytes()).hexdigest()
                   for path in extension.assets},
        "license": {"path": "third-party-notices/project-extension-" + extension.name + "-LICENSE.txt",
                    "sha256": hashlib.sha256(extension.license.read_bytes()).hexdigest()},
    }


def _registration(extensions):
    lines = ["// Generated from project metadata. Do not edit this staged file.",
             "import 'package:flet/flet.dart';"]
    for index, extension in enumerate(extensions):
        lines.append("import 'package:" + extension.name + "/" + extension.dart_entrypoint
                     + "' as project_" + str(index) + ";")
    lines.extend(["", "List<FletExtension> initializeProjectExtensions() {",
                  "  final extensions = <FletExtension>[];"])
    for index, extension in enumerate(extensions):
        lines.extend(["  try {", "    final extension = project_" + str(index) + "."
                      + extension.dart_extension + "();", "    extension.ensureInitialized();",
                      "    extensions.add(extension);", "  } catch (error, stack) {",
                      "    Error.throwWithStackTrace(StateError('Project extension "
                      + extension.name + " initialization failed: $error'), stack);", "  }"])
    lines.extend(["  return extensions;", "}", ""])
    return "\n".join(lines)


def stage_project_flutter(project, module):
    """Supplement a freshly staged SDK module; never modify project sources."""
    extensions = getattr(project, "extensions", ()) if project is not None else ()
    staging = module.parent / "project-extensions"
    if staging.exists():
        if staging.is_symlink() or not staging.is_dir():
            raise ValueError("Invalid project extension staging directory.")
        shutil.rmtree(staging)
    (module / "lib/project_extensions.dart").write_text(_registration(extensions), encoding="utf-8")
    if not extensions:
        return
    pubspec = _load_pubspec(module / "pubspec.yaml")
    dependencies = pubspec.setdefault("dependencies", {})
    dev_dependencies = pubspec.setdefault("dev_dependencies", {})
    overrides = pubspec.setdefault("dependency_overrides", {})
    # Project libraries target this exact SDK API, even when their pubspec uses
    # a hosted flet constraint. Preserve every retained paired package source.
    for name, source in dependencies.items():
        if name == "flet" or name.startswith("flet_"):
            overrides[name] = source
    selected = {extension.name for extension in extensions}
    source_inputs = {}
    for extension in extensions:
        if extension.name in dependencies or extension.name in overrides or extension.name in dev_dependencies:
            raise ValueError("Project extension collides with SDK Flutter dependency: " + extension.name)
        target = staging / extension.name
        shutil.copytree(extension.dart_package, target)
        if _load_pubspec(target / "pubspec.yaml") != extension.pubspec:
            raise ValueError("Project extension pubspec changed after validation; reload project: " + extension.name)
        source_inputs[extension.name] = _files(extension.dart_package)
        package_pubspec = json.loads(json.dumps(extension.pubspec))
        for field in ("dependencies", "dev_dependencies"):
            for name, source in package_pubspec.get(field, {}).items():
                if isinstance(source, dict) and "path" in source:
                    package_pubspec[field][name] = {"path": "../" + name}
        (target / "pubspec.yaml").write_text(yaml.safe_dump(package_pubspec, sort_keys=False), encoding="utf-8")
        dependencies[extension.name] = {"path": "../project-extensions/" + extension.name}
        tests = target / "test"
        if tests.is_dir():
            shutil.copytree(tests, module / "test/project_extensions" / extension.name)
            for name, source in package_pubspec.get("dev_dependencies", {}).items():
                if name in selected:
                    continue
                if name in dependencies:
                    if dependencies[name] != source and name not in overrides:
                        raise ValueError("Project test dependency conflicts with SDK dependency: " + name)
                    continue
                if name in dev_dependencies and dev_dependencies[name] != source:
                    raise ValueError("Project test dependency conflicts with SDK test dependency: " + name)
                dev_dependencies[name] = source
    (module / "pubspec.yaml").write_text(yaml.safe_dump(pubspec, sort_keys=False), encoding="utf-8")
    # Rewriting local dependencies normalizes YAML. Preserve the original byte
    # identity too, so edits to a package pubspec cannot reuse an older AAR.
    (staging / "source-inputs.json").write_text(json.dumps(source_inputs, sort_keys=True) + "\n", encoding="utf-8")

