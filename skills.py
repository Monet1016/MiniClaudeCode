from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SkillRecord:
    name: str
    description: str
    path: str
    content: str


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    metadata: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"').strip("'")
    return metadata, parts[2].strip()


def scan_skills(cwd: str) -> dict[str, SkillRecord]:
    skills_dir = Path(cwd) / "skills"
    records: dict[str, SkillRecord] = {}
    if not skills_dir.is_dir():
        return records

    for directory in sorted(skills_dir.iterdir()):
        if not directory.is_dir():
            continue
        manifest = directory / "SKILL.md"
        if not manifest.is_file():
            continue
        raw = manifest.read_text(encoding="utf-8")
        metadata, _body = _parse_frontmatter(raw)
        name = metadata.get("name", directory.name)
        description = metadata.get(
            "description",
            raw.splitlines()[0].lstrip("#").strip() if raw.splitlines() else directory.name,
        )
        records[name] = SkillRecord(
            name=name,
            description=description,
            path=str(manifest),
            content=raw,
        )
    return records


def load_skill(cwd: str, name: str) -> SkillRecord | None:
    return scan_skills(cwd).get(name)


def list_skills(cwd: str) -> list[SkillRecord]:
    records = scan_skills(cwd)
    return [records[name] for name in sorted(records)]
