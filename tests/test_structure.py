#!/usr/bin/env python3
"""Lightweight repository contract checks."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def require(path: Path) -> None:
    if not path.exists():
        fail(f"missing {path.relative_to(ROOT)}")


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        fail(f"{path.relative_to(ROOT)} missing YAML frontmatter")
    try:
        _, raw, _ = text.split("---", 2)
    except ValueError:
        fail(f"{path.relative_to(ROOT)} has invalid frontmatter fence")
    data: dict[str, str] = {}
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            fail(f"{path.relative_to(ROOT)} has invalid frontmatter line: {line}")
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def main() -> int:
    plugin_json = ROOT / ".codex-plugin" / "plugin.json"
    require(plugin_json)
    payload = json.loads(plugin_json.read_text(encoding="utf-8"))
    if payload.get("name") != "seo-agent-suite":
        fail("plugin name must be seo-agent-suite")
    if payload.get("skills") != "./skills/":
        fail("plugin skills path must be ./skills/")

    skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
    if len(skills) != 4:
        fail(f"expected 4 skills, found {len(skills)}")
    for skill in skills:
        data = parse_frontmatter(skill)
        name = data.get("name")
        if not name:
            fail(f"{skill.relative_to(ROOT)} missing name")
        if name != skill.parent.name:
            fail(f"{skill.relative_to(ROOT)} name does not match folder")
        if not data.get("description"):
            fail(f"{skill.relative_to(ROOT)} missing description")
        if re.search(r"\n|\[TODO:", data["description"]):
            fail(f"{skill.relative_to(ROOT)} invalid description")

    scripts = sorted((ROOT / "scripts").glob("*.py"))
    if not scripts:
        fail("missing Python scripts")
    subprocess.run([sys.executable, "-m", "py_compile", *map(str, scripts)], check=True)

    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
