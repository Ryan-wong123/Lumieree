#!/usr/bin/env python3
"""Fail when product/architecture-relevant files changed but PRD.md / architecture.md did not.

Modes (the rules mirror AGENTS.md):
    check_docs_updated.py <base-ref>            CI: files changed on this branch vs <base-ref> (e.g. origin/main)
    check_docs_updated.py --staged              pre-commit: files in the git index
    check_docs_updated.py --working-tree        uncommitted changes (staged + unstaged + untracked)
    check_docs_updated.py --working-tree --hook Claude Code "Stop" hook: reads the hook JSON on stdin and exits 2
                                                (message on stderr) so the agent keeps working until docs are updated

Escape hatches for changes that truly alter neither behaviour nor structure (formatting, comments, tests):
    * a commit-message line "Docs-Not-Needed: <reason>"  (CI / commit-range mode)
    * environment variable DOCS_CHECK_SKIP=1             (local modes)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

# Changes here alter the architecture (structure, data model, config, deployment, dependencies).
ARCH_TRIGGERS = (
    "lumieree/models.py",
    "lumieree/__init__.py",
    "lumieree/config.py",
    "lumieree/extensions.py",
    "lumieree/auth.py",
    "lumieree/blueprints/",
    "migrations/versions/",
    "Dockerfile",
    "docker-compose.yml",
    "k8s/",
    "requirements.txt",
    ".github/workflows/",
)
# Changes here alter what the product does for its users.
PRD_TRIGGERS = (
    "lumieree/blueprints/",
    "templates/",
    "lumieree/translations.py",
    "lumieree/auth.py",
    "lumieree/cli.py",
    "lumieree/legacy_import.py",
)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout  # noqa: S603, S607


def changed_files(mode: str, base: str | None) -> list[str]:
    if mode == "staged":
        return git("diff", "--cached", "--name-only").splitlines()
    if mode == "working-tree":
        names = set(git("diff", "--name-only", "HEAD").splitlines())
        names |= set(git("ls-files", "--others", "--exclude-standard").splitlines())
        return sorted(n for n in names if n)
    return [line for line in git("diff", "--name-only", f"{base}...HEAD").splitlines() if line]


def evaluate(changed: list[str]) -> list[str]:
    def touched(prefixes):
        return [f for f in changed if f.startswith(prefixes)]

    def short(files):
        return ", ".join(files[:6]) + (f" (+{len(files) - 6} more)" if len(files) > 6 else "")

    problems = []
    if touched(ARCH_TRIGGERS) and "architecture.md" not in changed:
        problems.append(f"architecture.md was not updated, but these changed: {short(touched(ARCH_TRIGGERS))}")
    if touched(PRD_TRIGGERS) and "PRD.md" not in changed:
        problems.append(f"PRD.md was not updated, but these changed: {short(touched(PRD_TRIGGERS))}")
    return problems


def main(argv: list[str]) -> int:
    hook = "--hook" in argv
    args = [a for a in argv if a != "--hook"]
    mode, base = "range", None
    if "--staged" in args:
        mode = "staged"
    elif "--working-tree" in args:
        mode = "working-tree"
    else:
        base = args[0] if args else "origin/main"

    if hook:
        try:
            payload = json.load(sys.stdin)
        except ValueError:
            payload = {}
        if payload.get("stop_hook_active"):  # already nudged once this turn: never loop forever
            return 0

    if os.environ.get("DOCS_CHECK_SKIP") == "1":
        print("DOCS_CHECK_SKIP=1: skipping documentation check.")
        return 0
    if mode == "range" and "Docs-Not-Needed:" in git("log", f"{base}..HEAD", "--format=%B"):
        print("Docs-Not-Needed trailer found; skipping.")
        return 0

    problems = evaluate(changed_files(mode, base))
    if not problems:
        print("Docs are in sync.")
        return 0

    message = (
        "Documentation is out of sync (see AGENTS.md > 'Documentation sync protocol'):\n"
        + "\n".join(f"  - {p}" for p in problems)
        + "\nUpdate the affected sections (and the Change log at the bottom of each file), then re-run this check."
    )
    print(message, file=sys.stderr if hook else sys.stdout)
    return 2 if hook else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
