#!/usr/bin/env python3
"""Validate the OCPP Agent Skill package.

Dependency-free: uses only the Python standard library. Run from anywhere:

    python3 scripts/validate_skill.py

Exit codes:
    0  no errors (warnings may be present)
    1  errors found
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = ROOT / "SKILL.md"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\s*\)")
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}

errors: list[str] = []
warnings: list[str] = []


def err(message: str) -> None:
    errors.append(message)


def warn(message: str) -> None:
    warnings.append(message)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        err(f"{rel(path)}: invalid UTF-8 ({exc})")
        return None
    except OSError as exc:
        err(f"{rel(path)}: cannot read ({exc})")
        return None


def is_ignored(path: Path) -> bool:
    # Only inspect the path relative to the package root. Absolute install paths
    # legitimately contain hidden directories such as ~/.claude or ~/.config.
    try:
        parts = path.resolve().relative_to(ROOT.resolve()).parts
    except ValueError:
        parts = path.parts
    return any(
        part in IGNORED_DIRS or (part.startswith(".") and part != ".github")
        for part in parts
    )


def parse_scalar(raw: str) -> object:
    raw = raw.strip()
    if not raw:
        return ""
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        return raw[1:-1]
    if raw in {"true", "True", "TRUE"}:
        return True
    if raw in {"false", "False", "FALSE"}:
        return False
    if raw in {"null", "Null", "NULL", "~"}:
        return None
    return raw


def parse_frontmatter(text: str) -> tuple[dict[str, object], str, str | None]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, "SKILL.md must start with a '---' frontmatter line"

    end: int | None = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text, "frontmatter has no closing '---' line"

    raw_lines = lines[1:end]
    data: dict[str, object] = {}
    index = 0
    while index < len(raw_lines):
        line = raw_lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if line.startswith((" ", "\t")):
            index += 1
            continue

        key, separator, rest = line.partition(":")
        if not separator:
            return {}, text, f"frontmatter line is not a key/value pair: {line!r}"
        key = key.strip()
        rest = rest.strip()

        if rest in {"|", "|-", "|+", ">", ">-", ">+"}:
            block: list[str] = []
            cursor = index + 1
            while cursor < len(raw_lines):
                candidate = raw_lines[cursor]
                if candidate.strip() and not candidate.startswith((" ", "\t")):
                    break
                block.append(candidate)
                cursor += 1
            non_empty = [item for item in block if item.strip()]
            indent = min((len(item) - len(item.lstrip(" ")) for item in non_empty), default=0)
            cleaned = [item[indent:] if len(item) >= indent else "" for item in block]
            if rest.startswith(">"):
                data[key] = " ".join(item.strip() for item in cleaned if item.strip())
            else:
                data[key] = "\n".join(cleaned).strip("\n")
            index = cursor
            continue

        value = parse_scalar(rest)
        if key == "metadata" and rest == "":
            metadata: dict[str, object] = {}
            cursor = index + 1
            while cursor < len(raw_lines):
                candidate = raw_lines[cursor]
                if candidate.strip() and not candidate.startswith((" ", "\t")):
                    break
                if candidate.strip():
                    meta_key, meta_sep, meta_value = candidate.strip().partition(":")
                    if not meta_sep:
                        return {}, text, f"metadata line is not a key/value pair: {candidate!r}"
                    metadata[meta_key.strip()] = parse_scalar(meta_value.strip())
                cursor += 1
            data["metadata"] = metadata
            index = cursor
            continue

        data[key] = value
        index += 1

    body = "\n".join(lines[end + 1 :])
    return data, body, None


def strip_fenced(text: str) -> str:
    result: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if not in_fence:
            result.append(line)
    return "\n".join(result)


def markdown_files() -> list[Path]:
    return sorted(path for path in ROOT.rglob("*.md") if not is_ignored(path))


def check_frontmatter() -> tuple[str, str]:
    if not SKILL_MD.is_file():
        err("SKILL.md not found at the package root")
        return "", ""

    text = read_text(SKILL_MD)
    if text is None:
        return "", ""

    data, body, problem = parse_frontmatter(text)
    if problem:
        err(f"SKILL.md: {problem}")
        return "", body

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        err("frontmatter: 'name' is required and must be a string")
        name = ""
    else:
        name = name.strip()
        if not NAME_RE.fullmatch(name):
            err("frontmatter: 'name' must be lowercase kebab-case (^[a-z0-9]+(-[a-z0-9]+)*$)")
        if len(name) > 64:
            err("frontmatter: 'name' must be at most 64 characters")
        if name != ROOT.name:
            err(f"frontmatter: 'name' ({name!r}) must match the directory ({ROOT.name!r})")
        if name == "synced":
            err("frontmatter: 'synced' is reserved by Claude Code")
        if name.startswith("anthropic-skills"):
            err("frontmatter: the 'anthropic-skills' namespace is reserved")

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        err("frontmatter: 'description' is required and must be a string")
        description = ""
    else:
        description = description.strip()
        if len(description) > 1024:
            err(f"frontmatter: 'description' is {len(description)} characters; the Agent Skills limit is 1024")
        if len(description) < 40:
            warn("frontmatter: 'description' is very short; it is the main trigger mechanism")

    if not data.get("license"):
        warn("frontmatter: no 'license' field (recommended for a published skill)")
    if not data.get("compatibility"):
        warn("frontmatter: no 'compatibility' field (recommended for a published skill)")
    if "metadata" in data and not isinstance(data["metadata"], dict):
        err("frontmatter: 'metadata' must be a mapping")

    body_lines = len(body.splitlines())
    if body_lines > 500:
        warn(f"SKILL.md: {body_lines} body lines; keep the entry point under 500 where possible")
    if body_lines > 800:
        err(f"SKILL.md: {body_lines} body lines; move detail into references/")
    if not re.search(r"^#\s+\S", body, re.MULTILINE):
        warn("SKILL.md: no level-1 heading found")

    return name, description


def check_files() -> list[Path]:
    all_files = [
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not is_ignored(path)
    ]
    for path in all_files:
        if path.stat().st_size == 0:
            err(f"{rel(path)}: file is empty")
        if path.suffix.lower() in {".md", ".json", ".yml", ".yaml", ".py", ".sh", ".txt"}:
            read_text(path)
    return all_files


def check_links() -> tuple[int, dict[Path, list[Path]]]:
    graph: dict[Path, list[Path]] = {}
    link_count = 0

    for path in markdown_files():
        text = read_text(path)
        if text is None:
            continue
        text = strip_fenced(text)
        targets: list[Path] = []
        for match in LINK_RE.finditer(text):
            raw_target = match.group(1).strip()
            if raw_target.startswith(("http://", "https://", "mailto:", "tel:", "#")):
                continue
            if raw_target.startswith("/"):
                continue

            clean = unquote(raw_target.split("#", 1)[0])
            if not clean:
                continue

            destination = (path.parent / clean).resolve()
            link_count += 1
            if not destination.exists():
                err(f"{rel(path)}: broken local link -> {raw_target}")
            targets.append(destination)
        graph[path.resolve()] = targets

    return link_count, graph


def check_reference_reachability(graph: dict[Path, list[Path]]) -> int:
    references = sorted((ROOT / "references").rglob("*.md"))
    if not references:
        warn("no references/ directory or no Markdown files in it")
        return 0

    start = SKILL_MD.resolve()
    seen: set[Path] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for target in graph.get(current, []):
            if target.suffix.lower() == ".md" and str(target).startswith(str(ROOT.resolve())):
                stack.append(target)

    for reference in references:
        if reference.resolve() not in seen:
            warn(f"{rel(reference)}: not reachable from SKILL.md by a Markdown link")

    return len(references)


def check_long_files() -> None:
    for path in markdown_files():
        if path.name == "README.md":
            continue
        text = read_text(path)
        if text is None:
            continue
        lines = len(text.splitlines())
        if lines > 300 and "## Contents" not in text and "## Table of contents" not in text:
            warn(f"{rel(path)}: {lines} lines; add a '## Contents' table for navigation")


def check_json() -> int:
    count = 0
    for path in sorted(ROOT.rglob("*.json")):
        if is_ignored(path):
            continue
        text = read_text(path)
        if text is None:
            continue
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            err(f"{rel(path)}: invalid JSON ({exc})")
        else:
            count += 1
    return count


def main() -> int:
    print("OCPP skill validation")
    print(f"  package: {ROOT}")
    print()

    name, description = check_frontmatter()
    files = check_files()
    link_count, graph = check_links()
    reference_count = check_reference_reachability(graph)
    check_long_files()
    json_count = check_json()

    print(f"  name:          {name or '(missing)'}")
    print(f"  description:   {len(description)} characters")
    print(f"  files:         {len(files)}")
    print(f"  references:    {reference_count}")
    print(f"  local links:   {link_count}")
    print(f"  JSON files:    {json_count}")
    print()

    for message in warnings:
        print(f"warning: {message}")
    for message in errors:
        print(f"error: {message}")

    if errors:
        print()
        print(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1

    print(f"OK: {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
