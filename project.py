"""Validate application sources kept outside the fixed SDK runtime."""

import json
import keyword
import re
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FIELDS = {"application_id", "display_name", "version_code", "version_name",
          "startup_template", "game_dir", "python_dir", "assets_dir", "app_home", "icon"}
REQUIRED_FIELDS = FIELDS - {"app_home", "icon"}
GENERATED_NAMES = {".git", ".android-build", ".venv", "venv", "__pycache__",
                   ".pytest_cache", ".mypy_cache", ".ruff_cache", "saves", "cache",
                   "build", "dist", "node_modules"}
GENERATED_SUFFIXES = {".pyc", ".pyo", ".rpyc", ".rpymc", ".rpa", ".apk", ".aab",
                      ".aar", ".jar", ".class", ".so", ".pyd", ".dll", ".dylib",
                      ".pth", ".egg-link"}
PRIVATE_NAMES = {"main", "lib", "renpy", "flet", "flet-assets", "third-party-notices",
                 "data", "flet.sock", "flet_extensions.json", "project-notice.txt"}
SDK_PACKAGES = {"android", "jnius", "pygame", "pygame_sdl2", "store", "_renpy",
                "_renpybidi", "_renpystyle", "httpx", "httpcore", "h11", "oauthlib",
                "repath", "msgpack", "anyio", "certifi", "idna", "six",
                "typing_extensions", "jinja2", "markupsafe", "sitecustomize", "usercustomize"}


@dataclass(frozen=True)
class Project:
    path: Path
    application_id: str
    display_name: str
    version_code: int
    version_name: str
    startup_template: str
    game_dir: Path
    python_dir: Path
    assets_dir: Path
    app_home: str | None
    icon: Path | None


def generated_entry(name):
    lower = name.casefold()
    return (lower in GENERATED_NAMES or Path(lower).suffix in GENERATED_SUFFIXES
            or lower.endswith((".dist-info", ".egg-info")))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate project config field: " + key)
        result[key] = value
    return result


def _source_path(root, field, value, *, directory=True):
    if (not isinstance(value, str) or not value or value != value.strip()
            or "\\" in value or "\0" in value):
        raise ValueError(field + " must be a relative project path.")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts or relative == Path("."):
        raise ValueError(field + " must stay inside the project directory.")
    if any(generated_entry(part) for part in relative.parts):
        raise ValueError(field + " cannot select generated or native output.")
    candidate = root
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ValueError(field + " cannot contain symlinks.")
    if not candidate.exists() or not candidate.resolve().is_relative_to(root):
        raise ValueError(field + " must exist inside the project directory.")
    mode = candidate.stat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise ValueError(field + (" must be a regular directory." if directory
                                 else " must be a regular file."))
    return candidate.resolve()


def _source_tree(root):
    for path in root.rglob("*"):
        if (path.is_symlink() or not (path.is_file() or path.is_dir())
                or not path.name.isprintable() or "\\" in path.name):
            raise ValueError("Source trees cannot contain links or special/unsafe entries.")
        try:
            path.name.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Source filenames must contain valid Unicode text.") from None
        if generated_entry(path.name):
            raise ValueError("Remove generated or native output from project sources: "
                             + path.relative_to(root).as_posix())


def _reserved_modules():
    extensions = json.loads((ROOT / "runtime/flet_extensions.json").read_text())
    return (PRIVATE_NAMES | SDK_PACKAGES | set(sys.stdlib_module_names)
            | {path.stem.casefold() for path in (ROOT / "runtime").glob("*.py")}
            | {name.replace("-", "_") for name in extensions})


def _python_names(root, reserved, *, game=False):
    names = set()
    for path in root.iterdir():
        if game and not (path.suffix == ".py" or (path.is_dir() and any(path.rglob("*.py")))):
            continue
        name = path.stem if path.is_file() and path.suffix == ".py" else path.name
        if name.casefold() in reserved:
            raise ValueError("Project Python cannot shadow SDK or standard-library names: " + name)
        names.add(name.casefold())
    return names


def _png(path):
    with path.open("rb") as stream:
        header = stream.read(33)
    if (path.suffix.casefold() != ".png" or len(header) != 33
            or header[:8] != b"\x89PNG\r\n\x1a\n" or header[8:16] != b"\0\0\0\rIHDR"):
        raise ValueError("icon must be an existing PNG image.")
    width, height = struct.unpack(">II", header[16:24])
    if not (1 <= width <= 8192 and 1 <= height <= 8192):
        raise ValueError("icon PNG dimensions must be between 1 and 8192 pixels.")


def load_project(config_path):
    """Read a strict JSON file without importing or executing application code.

    ``Project.path`` is the resolved config file; its parent owns all supplied
    sources. The builder generates immutable runtime configuration from it.
    """
    path = Path(config_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Project config must be a regular JSON file.")
    path = path.resolve()
    try:
        config = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Project config must contain valid UTF-8 JSON.") from error
    if not isinstance(config, dict):
        raise ValueError("Project config must be an object.")
    if set(config) - FIELDS:
        raise ValueError("Unknown project config fields: " + ", ".join(sorted(set(config) - FIELDS)))
    if REQUIRED_FIELDS - set(config):
        raise ValueError("Missing project config fields: " + ", ".join(sorted(REQUIRED_FIELDS - set(config))))
    application_id = config["application_id"]
    if (not isinstance(application_id, str) or len(application_id) > 150
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", application_id)):
        raise ValueError("application_id needs at least two ASCII Android package segments.")
    display_name = config["display_name"]
    if (not isinstance(display_name, str) or not 1 <= len(display_name) <= 80
            or display_name != display_name.strip() or not display_name.isprintable()):
        raise ValueError("display_name must contain 1 to 80 printable characters.")
    try:
        display_name.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("display_name must contain valid Unicode text.") from None
    version_code = config["version_code"]
    if type(version_code) is not int or not 1 <= version_code <= 2100000000:
        raise ValueError("version_code must be an integer from 1 to 2100000000.")
    version_name = config["version_name"]
    if (not isinstance(version_name, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,49}", version_name)):
        raise ValueError("version_name must use 1 to 50 ASCII letters, digits or ._+-.")
    if config["startup_template"] not in ("story", "app"):
        raise ValueError("startup_template must be story or app.")
    root = path.parent
    sources = {field: _source_path(root, field, config[field])
               for field in ("game_dir", "python_dir", "assets_dir")}
    for field, source in sources.items():
        for other, directory in sources.items():
            if field != other and source.is_relative_to(directory):
                raise ValueError("Project source directories must not overlap.")
        _source_tree(source)
    if not any(sources["game_dir"].rglob("*.rpy")):
        raise ValueError("game_dir must contain a native .rpy source file.")
    if (sources["game_dir"] / "_renfletpy_project.rpy").exists():
        raise ValueError("game/_renfletpy_project.rpy is reserved for generated identity.")
    reserved = _reserved_modules()
    python_names = _python_names(sources["python_dir"], reserved)
    game_names = _python_names(sources["game_dir"], reserved, game=True)
    if game_names & python_names:
        raise ValueError("Ambiguous project Python names across game_dir and python_dir: "
                         + ", ".join(sorted(game_names & python_names)))
    app_home = config.get("app_home")
    if app_home is not None:
        if not isinstance(app_home, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*:[A-Za-z_][A-Za-z0-9_]*", app_home):
            raise ValueError("app_home must be null or a top-level module:function.")
        module, factory = app_home.split(":")
        if keyword.iskeyword(module) or keyword.iskeyword(factory):
            raise ValueError("app_home needs valid Python module and function names.")
        if not (sources["python_dir"] / (module + ".py")).is_file():
            raise ValueError("app_home module must exist directly inside python_dir.")
    icon = config.get("icon")
    if icon is not None:
        icon = _source_path(root, "icon", icon, directory=False)
        _png(icon)
        if (sources["assets_dir"] / "_renfletpy_project_icon.png").exists():
            raise ValueError("assets/_renfletpy_project_icon.png is reserved for the supplied icon.")
    return Project(path=path, application_id=application_id, display_name=display_name,
                   version_code=version_code, version_name=version_name,
                   startup_template=config["startup_template"], app_home=app_home, icon=icon,
                   **sources)
