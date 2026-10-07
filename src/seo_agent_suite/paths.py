"""Locate the suite checkout root and legacy scripts/ directory."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def suite_root() -> Path:
    """Return the repository / plugin root that contains skills/ and scripts/.

    Resolution order:
    1. Walk up from this package looking for scripts/repo_seo_baseline.py
       (editable install or source checkout).
    2. Fall back to parents of the package (src/seo_agent_suite → repo root).
    """
    here = package_dir()
    for candidate in (here, *here.parents):
        marker = candidate / "scripts" / "repo_seo_baseline.py"
        if marker.is_file():
            return candidate
    if here.parent.name == "src":
        return here.parent.parent
    return here.parent


def scripts_dir() -> Path:
    spec = importlib.util.find_spec("seo_agent_suite.collectors")
    if spec is not None and spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations)))
    root = suite_root()
    path = root / "scripts"
    if not path.is_dir():
        raise FileNotFoundError(
            f"SEO Agent Suite scripts/ not found under {root}. "
            "Run from a source checkout or install the package editable "
            "(`pip install -e .`) so scripts remain next to the package."
        )
    return path


def ensure_scripts_on_path() -> Path:
    """Put scripts/ on sys.path so legacy modules (public_http, …) import."""
    path = scripts_dir()
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)
    return path


def load_script(name: str):
    """Load a legacy script module by filename (e.g. site_meta_audit.py).

    Uses the script's natural module name (`public_http`, `site_meta_audit`, …)
    so CLI, tests, and `import public_http` inside scripts share one module
    identity. Re-loading under a second name would break HTTP mocks.
    """
    ensure_scripts_on_path()
    path = scripts_dir() / name
    if not path.is_file():
        raise FileNotFoundError(f"missing script: {path}")
    mod_name = path.stem
    existing = sys.modules.get(mod_name)
    if existing is not None and getattr(existing, "__file__", None):
        existing_path = Path(existing.__file__).resolve()
        if existing_path == path.resolve():
            return existing
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module
