#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


DEFAULT_TEMPLATE_DIR = Path("skills/job_buddy_agent_template")
DEFAULT_TARGET_DIR = Path("skills-local/job_buddy_agent")


def copy_skill_template(template_dir: Path, target_dir: Path, force: bool = False) -> Path:
    template_dir = template_dir.resolve()
    target_dir = target_dir.resolve()
    references_dir = template_dir / "references"

    if not template_dir.exists():
        raise FileNotFoundError(f"template dir not found: {template_dir}")
    if not references_dir.exists():
        raise FileNotFoundError(f"template references dir not found: {references_dir}")
    if target_dir.exists():
        if not force:
            raise FileExistsError(f"target dir already exists: {target_dir}")
        shutil.rmtree(target_dir)

    (target_dir / "references").mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_dir / "SKILL.md", target_dir / "SKILL.md")

    readme_path = template_dir / "README.md"
    if readme_path.exists():
        shutil.copy2(readme_path, target_dir / "README.md")

    for source in references_dir.iterdir():
        if source.is_dir():
            continue
        if source.name.endswith(".example"):
            destination_name = source.name.removesuffix(".example")
        else:
            destination_name = source.name
        shutil.copy2(source, target_dir / "references" / destination_name)

    return target_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a local private Job Buddy skill from the template.")
    parser.add_argument(
        "--template",
        default=str(DEFAULT_TEMPLATE_DIR),
        help="Path to the template skill directory.",
    )
    parser.add_argument(
        "--target",
        default=str(DEFAULT_TARGET_DIR),
        help="Path to the generated local private skill directory.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the target directory if it already exists.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    target_dir = copy_skill_template(
        template_dir=Path(args.template),
        target_dir=Path(args.target),
        force=args.force,
    )
    print(f"Skill generated at: {target_dir}")
    print("Next steps:")
    print(f"1. Edit {target_dir / 'references' / 'my_resume.md'}")
    print(f"2. Edit {target_dir / 'references' / 'job_preferences.md'}")
    print(f"3. Edit {target_dir / 'references' / 'greeting_style.md'}")


if __name__ == "__main__":
    main()
