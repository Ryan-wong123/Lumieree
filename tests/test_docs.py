"""Keeps architecture.md honest: everything the code defines must be documented (see AGENTS.md)."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ARCH = (ROOT / "architecture.md").read_text(encoding="utf-8")
PRD = (ROOT / "PRD.md").read_text(encoding="utf-8")


def test_every_route_is_documented(app):
    missing = [r.rule for r in app.url_map.iter_rules() if f"`{r.rule}`" not in ARCH]
    assert not missing, f"Add these routes to the route inventory in architecture.md: {missing}"


def test_documented_routes_exist(app):
    documented = set(re.findall(r"^\| `(/[^`]*)` \|", ARCH, flags=re.M))
    actual = {r.rule for r in app.url_map.iter_rules()}
    stale = documented - actual
    assert not stale, f"architecture.md lists routes that no longer exist: {sorted(stale)}"


def test_every_table_is_documented(app):
    from lumieree.extensions import db

    missing = [t for t in db.metadata.tables if f"`{t}`" not in ARCH]
    assert not missing, f"Add these tables to the data model section of architecture.md: {missing}"


def test_every_env_var_is_documented():
    source = (ROOT / "lumieree" / "config.py").read_text(encoding="utf-8")
    cli = (ROOT / "lumieree" / "cli.py").read_text(encoding="utf-8")
    names = set(re.findall(r'(?:environ\.get|_bool)\(\s*"([A-Z][A-Z0-9_]+)"', source + cli))
    names |= set(re.findall(r'os\.environ\.get\(\s*"([A-Z][A-Z0-9_]+)"', cli))
    missing = sorted(n for n in names if n not in ARCH)
    assert not missing, f"Add these environment variables to the configuration table in architecture.md: {missing}"


def test_every_blueprint_module_is_documented():
    modules = [p.stem for p in (ROOT / "lumieree" / "blueprints").glob("*.py") if p.stem != "__init__"]
    missing = [m for m in modules if f"{m}.py" not in ARCH]
    assert not missing, f"Mention these blueprint modules in the repository layout of architecture.md: {missing}"


def test_every_cli_command_is_documented(app):
    commands = [name for name in app.cli.commands if name not in {"db"}]
    missing = [c for c in commands if c not in ARCH]
    assert not missing, f"Document these CLI commands in architecture.md: {missing}"


@pytest.mark.parametrize("name,text", [("architecture.md", ARCH), ("PRD.md", PRD)])
def test_docs_have_a_change_log(name, text):
    assert re.search(r"^## .*Change log", text, flags=re.M | re.I), f"{name} must keep a Change log section"
