from __future__ import annotations

from pathlib import Path

import pytest

from scripts.setup_skill import copy_skill_template


def make_template(root: Path) -> Path:
    template = root / "skills" / "job_buddy_agent_template"
    references = template / "references"
    references.mkdir(parents=True)
    (template / "SKILL.md").write_text("skill-body\n", encoding="utf-8")
    (template / "README.md").write_text("template-readme\n", encoding="utf-8")
    (references / "my_resume.md.example").write_text("resume\n", encoding="utf-8")
    (references / "job_preferences.md.example").write_text("prefs\n", encoding="utf-8")
    (references / "greeting_style.md.example").write_text("style\n", encoding="utf-8")
    (references / "workflow_examples.md").write_text("workflow\n", encoding="utf-8")
    return template


def test_copy_skill_template_creates_private_skill(tmp_path: Path):
    template = make_template(tmp_path)
    target = tmp_path / "skills-local" / "job_buddy_agent"

    created = copy_skill_template(template, target)

    assert created == target.resolve()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "skill-body\n"
    assert (target / "README.md").read_text(encoding="utf-8") == "template-readme\n"
    assert (target / "references" / "my_resume.md").read_text(encoding="utf-8") == "resume\n"
    assert (target / "references" / "job_preferences.md").read_text(encoding="utf-8") == "prefs\n"
    assert (target / "references" / "greeting_style.md").read_text(encoding="utf-8") == "style\n"
    assert (target / "references" / "workflow_examples.md").read_text(encoding="utf-8") == "workflow\n"


def test_copy_skill_template_refuses_to_overwrite_without_force(tmp_path: Path):
    template = make_template(tmp_path)
    target = tmp_path / "skills-local" / "job_buddy_agent"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("old\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        copy_skill_template(template, target)


def test_copy_skill_template_overwrites_with_force(tmp_path: Path):
    template = make_template(tmp_path)
    target = tmp_path / "skills-local" / "job_buddy_agent"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("old\n", encoding="utf-8")

    copy_skill_template(template, target, force=True)

    assert (target / "SKILL.md").read_text(encoding="utf-8") == "skill-body\n"
