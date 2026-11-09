from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from vector_harness.core.loop import Loop


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """解析 ``SKILL.md`` 开头的 YAML 风格前言。缺名字或说明时返回 None。"""
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
        """技能目录。读取时才扫文件，构造时不加载。"""
        self.directory = directory

    def _load(self) -> dict[str, _Skill]:
        """收集目录下的 ``*.md`` 和一层 ``SKILL.md``。同名时后读到的覆盖先读到的。"""
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
        """生成放进系统提示的技能索引。目录不存在时返回空字符串。"""
        if not self.directory.is_dir():
            return ""
        skills = self._load()
        lines = ["Skills:"]
        for name in sorted(skills):
            lines.append(f"- {name}: {skills[name].description}")
        return "\n".join(lines)

    def read_tool(self) -> _ReadSkill:
        """返回按名字读取技能正文的工具。"""
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
        """按名字返回技能正文。找不到时返回固定的未知技能错误。"""
        skill_name = arguments.get("name", "")
        if not isinstance(skill_name, str):
            skill_name = str(skill_name)
        loaded = self.skills._load()
        skill = loaded.get(skill_name)
        if skill is None:
            return f"Error: Unknown skill: {skill_name}"
        return skill.body


def attach_skills(loop: Loop, directory: Path) -> None:
    """把技能索引进系统提示，并装上 ``read_skill``。同名工具就地替换。"""
    skills = Skills(directory)
    loop.install_prompt(skills.index_prompt())
    loop.replace_tool(skills.read_tool())
