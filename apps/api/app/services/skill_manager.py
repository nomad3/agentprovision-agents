"""SkillManager — scans the skills directory and loads file-based skill definitions."""
import json
import logging
import os
import re
import subprocess
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

    def create_skill(self, name: str, description: str, engine: str, script: str, inputs: list) -> dict:
        """Create a new file-based skill on disk and reload."""
        if self.get_skill_by_name(name):
            return {"error": f"Skill '{name}' already exists."}

        slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
        if not slug:
            return {"error": "Invalid skill name."}

        skill_dir = SKILLS_DIR / slug
        if skill_dir.exists():
            return {"error": f"Directory '{slug}' already exists."}

        # Engine-specific script filename
        script_filenames = {
            "python": "script.py",
            "shell": "script.sh",
            "markdown": "prompt.md",
        }
        script_file = script_filenames.get(engine, "script.py")

        try:
            skill_dir.mkdir(parents=True, exist_ok=True)

            frontmatter = {
                "name": name,
                "engine": engine,
                "script_path": script_file,
            }
            if inputs:
                frontmatter["inputs"] = inputs

            md_content = "---\n" + yaml.dump(frontmatter, default_flow_style=False) + "---\n\n"
            md_content += f"## Description\n{description}\n"

            (skill_dir / "skill.md").write_text(md_content, encoding="utf-8")
            (skill_dir / script_file).write_text(script, encoding="utf-8")

            # Make shell scripts executable
            if engine == "shell":
                os.chmod(skill_dir / script_file, 0o755)

            self.scan()

            created = self.get_skill_by_name(name)
            if created:
                return {"skill": created}
            return {"error": "Skill created but failed to load — check format."}
        except Exception as e:
            logger.exception("Failed to create skill: %s", e)
            return {"error": f"Failed to create skill: {str(e)}"}

    def execute_skill(self, name: str, inputs: dict) -> dict:
        """Execute a file-based skill by name with given inputs."""
        skill = self.get_skill_by_name(name)
        if not skill:
            available = [s.name for s in self._skills]
            return {"error": f"Skill '{name}' not found. Available: {available}"}

        script_path = os.path.join(skill.skill_dir, skill.script_path)
        if not os.path.exists(script_path):
            return {"error": f"Script not found: {script_path}"}

        try:
            if skill.engine == "python":
                return self._execute_python(name, script_path, inputs)
            elif skill.engine == "shell":
                return self._execute_shell(name, script_path, inputs)
            elif skill.engine == "markdown":
                return self._execute_markdown(name, script_path, inputs)
            else:
                return {"error": f"Unsupported engine: {skill.engine}"}
        except Exception as e:
            logger.exception("Skill execution failed: %s", e)
            return {"error": f"Skill execution failed: {str(e)}"}

    def _execute_python(self, name: str, script_path: str, inputs: dict) -> dict:
        import importlib.util

        spec = importlib.util.spec_from_file_location("skill_script", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "execute"):
            return {"error": "Skill script has no 'execute' function."}

        result = module.execute(inputs)
        return {"success": True, "skill": name, "result": result}

    def _execute_shell(self, name: str, script_path: str, inputs: dict) -> dict:
        env = os.environ.copy()
        for k, v in inputs.items():
            env[f"SKILL_INPUT_{k.upper()}"] = str(v)

        proc = subprocess.run(
            ["bash", script_path],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )

        if proc.returncode != 0:
            return {"error": f"Shell script exited with code {proc.returncode}", "stderr": proc.stderr[:2000]}

        # Try to parse output as JSON, otherwise return raw
        try:
            result = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError):
            result = {"output": proc.stdout.strip()}

        return {"success": True, "skill": name, "result": result}

    def _execute_markdown(self, name: str, script_path: str, inputs: dict) -> dict:
        content = Path(script_path).read_text(encoding="utf-8")
        # Substitute {{input_name}} placeholders with actual values
        for k, v in inputs.items():
            content = content.replace(f"{{{{{k}}}}}", str(v))
        return {"success": True, "skill": name, "result": {"prompt": content}}


# Module-level singleton
skill_manager = SkillManager.get_instance()
