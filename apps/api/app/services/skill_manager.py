"""File-based skill manager — scans the skills/ directory and loads skill.md definitions."""
import logging
import os
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent.parent / "skills"


class SkillInput(BaseModel):
    name: str
    type: str
    description: str
    required: bool = False


class FileSkill(BaseModel):
    id: str              # directory name, e.g. "hello_world"
    name: str
    engine: str
    script_path: str
    description: str
    inputs: List[SkillInput] = []


class SkillManager:
    """Singleton that loads all file-based skill definitions on startup."""

    _instance: Optional["SkillManager"] = None
    _skills: List[FileSkill] = []

    def __new__(cls) -> "SkillManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self, skills_dir: Path = _SKILLS_DIR) -> None:
        """Scan skills_dir and parse every skill.md found."""
        self._skills = []
        if not skills_dir.is_dir():
            logger.warning("Skills directory not found: %s", skills_dir)
            return

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "skill.md"
            if not skill_md.exists():
                continue
            try:
                skill = self._parse_skill(skill_dir.name, skill_md)
                self._skills.append(skill)
                logger.info("Loaded file skill: %s (%s)", skill.name, skill_dir.name)
            except Exception as exc:
                logger.error("Failed to load skill from %s: %s", skill_md, exc)

    def list_skills(self) -> List[FileSkill]:
        return list(self._skills)

    @staticmethod
    def _parse_skill(skill_id: str, skill_md: Path) -> FileSkill:
        content = skill_md.read_text(encoding="utf-8")

        # Split YAML frontmatter from Markdown body
        if not content.startswith("---"):
            raise ValueError("Missing YAML frontmatter (expected leading '---')")

        parts = content.split("---", 2)
        # parts[0] is empty, parts[1] is YAML, parts[2] is Markdown body
        if len(parts) < 3:
            raise ValueError("Malformed frontmatter — closing '---' not found")

        frontmatter = yaml.safe_load(parts[1])
        markdown_body = parts[2].strip()

        if not isinstance(frontmatter, dict):
            raise ValueError("Frontmatter did not parse as a YAML mapping")

        inputs = [
            SkillInput(**inp) for inp in frontmatter.get("inputs", [])
        ]

        return FileSkill(
            id=skill_id,
            name=frontmatter["name"],
            engine=frontmatter["engine"],
            script_path=frontmatter["script_path"],
            description=markdown_body,
            inputs=inputs,
        )


# Module-level singleton
skill_manager = SkillManager()
