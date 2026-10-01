"""brew_blocked packages must not creep back into any install list or alias.

trash-cli is blocked because `rm` aliased to `trash` sent every deletion on
the fleet to ~/.local/share/Trash, which filled punjab's disk (2026-09-26).
"""
from pathlib import Path

import yaml

from conftest import REPO

INSTALL_LISTS = ("core_brews", "core_tap_brews", "desktop_brews", "extra_brews", "desktop_casks")


def _vars_files():
    yield REPO / "group_vars" / "all.yml"
    yield from sorted((REPO / "group_vars").glob("*.yml"))
    yield from sorted((REPO / "host_vars").glob("*.yml"))


def _blocked():
    return set(yaml.safe_load((REPO / "group_vars" / "all.yml").read_text())["brew_blocked"])


def test_trash_cli_is_blocked():
    assert "trash-cli" in _blocked()


def test_no_install_list_names_a_blocked_package():
    blocked = _blocked()
    hits = []
    for path in _vars_files():
        data = yaml.safe_load(path.read_text()) or {}
        for key in INSTALL_LISTS:
            for pkg in data.get(key) or []:
                if pkg.rsplit("/", 1)[-1] in blocked:
                    hits.append(f"{path.relative_to(REPO)}:{key}:{pkg}")
    assert not hits, hits


def test_no_alias_routes_through_trash():
    groups = yaml.safe_load((REPO / "roles" / "shell_dotfiles" / "vars" / "main.yml").read_text())["alias_groups"]
    assert all(g.get("guard") != "trash" for g in groups)
    cmds = [a["cmd"] for g in groups for a in g.get("aliases", [])]
    assert not [c for c in cmds if c.split()[0] in {"trash", "trash-put"}]
