from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    if not text.startswith("---\n"):
        return None
    rest = text[4:]
    marker = rest.find("\n---\n")
    if marker < 0:
        return None
    raw = rest[:marker]
    body = rest[marker + 5 :]
    meta: dict[str, str] = {}
    for line in raw.split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key:
            meta[key] = value.strip()
    if not meta.get("name") or not meta.get("description"):
        return None
    return meta, body


@dataclass
class _Skill:
    name: str
    description: str
    body: str


class Skills:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _load(self) -> dict[str, _Skill]:
        found: dict[str, _Skill] = {}
        if not self.directory.is_dir():
            return found
        paths = list(self.directory.glob("*.md"))
        paths.extend(self.directory.glob("*/SKILL.md"))
        for path in paths:
            if not path.is_file():
                continue
            parsed = _parse_frontmatter(path.read_text(encoding="utf-8"))
            if parsed is None:
                continue
            meta, body = parsed
            name = meta["name"]
            found[name] = _Skill(name=name, description=meta["description"], body=body)
        return found

    def index_prompt(self) -> str:
        if not self.directory.is_dir():
            return ""
        skills = self._load()
        lines = ["Skills:"]
        for name in sorted(skills):
            lines.append(f"- {name}: {skills[name].description}")
        return "\n".join(lines)

    def read_tool(self) -> _ReadSkill:
        return _ReadSkill(self)


@dataclass
class _ReadSkill:
    skills: Skills
    name: str = "read_skill"
    description: str = "Read a skill by name."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
    )

    async def execute(self, arguments: dict) -> str:
        skill_name = arguments.get("name", "")
        if not isinstance(skill_name, str):
            skill_name = str(skill_name)
        loaded = self.skills._load()
        skill = loaded.get(skill_name)
        if skill is None:
            return f"Error: Unknown skill: {skill_name}"
        return skill.body
