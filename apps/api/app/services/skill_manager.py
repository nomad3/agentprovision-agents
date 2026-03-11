"""SkillManager — scans the skills directory and loads file-based skill definitions."""
import logging
import os
from pathlib import Path
from typing import List, Optional

import yaml

from app.schemas.file_skill import FileSkill, SkillInput

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _parse_skill_md(skill_dir: Path) -> Optional[FileSkill]:
    """Parse a skill.md file and return a FileSkill, or None if malformed."""
    skill_file = skill_dir / "skill.md"
    if not skill_file.exists():
        return None
    try:
        content = skill_file.read_text(encoding="utf-8")
        if not content.startswith("---"):
            logger.warning("Skipping %s: no YAML frontmatter found.", skill_file)
            return None

        # Split frontmatter from body
        parts = content.split("---", 2)
        if len(parts) < 3:
            logger.warning("Skipping %s: malformed frontmatter.", skill_file)
            return None

        frontmatter_raw = parts[1].strip()
        body = parts[2].strip()

        metadata = yaml.safe_load(frontmatter_raw)
        if not isinstance(metadata, dict):
            logger.warning("Skipping %s: frontmatter is not a mapping.", skill_file)
            return None

        # Parse description from Markdown body (strip the "## Description" header)
        description = body
        if description.startswith("## Description"):
            description = description[len("## Description"):].strip()

        # Parse inputs
        raw_inputs = metadata.get("inputs", []) or []
        inputs = [
            SkillInput(
                name=inp.get("name", ""),
                type=inp.get("type", "string"),
                description=inp.get("description", ""),
                required=bool(inp.get("required", False)),
            )
            for inp in raw_inputs
            if isinstance(inp, dict)
        ]

        return FileSkill(
            name=metadata["name"],
            engine=metadata.get("engine", "python"),
            script_path=metadata.get("script_path", "script.py"),
            description=description or None,
            inputs=inputs,
            skill_dir=str(skill_dir),
        )
    except Exception as exc:
        logger.error("Error loading skill from %s: %s", skill_dir, exc)
        return None


class SkillManager:
    """Singleton service that loads all file-based skills on startup."""

    _instance: Optional["SkillManager"] = None

    def __init__(self) -> None:
        self._skills: List[FileSkill] = []

    @classmethod
    def get_instance(cls) -> "SkillManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def scan(self) -> None:
        """Scan the skills directory and load all valid skill definitions."""
        loaded: List[FileSkill] = []
        if not SKILLS_DIR.is_dir():
            logger.warning("Skills directory not found: %s", SKILLS_DIR)
            self._skills = loaded
            return

        for entry in sorted(SKILLS_DIR.iterdir()):
            if entry.is_dir():
                skill = _parse_skill_md(entry)
                if skill:
                    loaded.append(skill)
                    logger.info("Loaded skill: %s (dir=%s)", skill.name, entry.name)

        self._skills = loaded
        logger.info("SkillManager: %d skill(s) loaded.", len(self._skills))

    def list_skills(self) -> List[FileSkill]:
        """Return all loaded skill definitions."""
        return list(self._skills)

    def get_skill_by_name(self, name: str) -> Optional[FileSkill]:
        """Find a skill by name (case-insensitive)."""
        for skill in self._skills:
            if skill.name.lower() == name.lower():
                return skill
        return None

    def execute_skill(self, name: str, inputs: dict) -> dict:
        """Execute a file-based skill by name with given inputs."""
        import importlib.util

        skill = self.get_skill_by_name(name)
        if not skill:
            available = [s.name for s in self._skills]
            return {"error": f"Skill '{name}' not found. Available: {available}"}

        script_path = os.path.join(skill.skill_dir, skill.script_path)
        if not os.path.exists(script_path):
            return {"error": f"Script not found: {script_path}"}

        try:
            spec = importlib.util.spec_from_file_location("skill_script", script_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, "execute"):
                return {"error": f"Skill script has no 'execute' function."}

            result = module.execute(inputs)
            return {"success": True, "skill": name, "result": result}
        except Exception as e:
            logger.exception("Skill execution failed: %s", e)
            return {"error": f"Skill execution failed: {str(e)}"}


# Module-level singleton
skill_manager = SkillManager.get_instance()
