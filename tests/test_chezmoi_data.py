import yaml

from conftest import REPO


def load(rel):
    return yaml.safe_load((REPO / rel).read_text())


def test_identity_matches_ansible_vars():
    # group_vars/all.yml feeds ssh_keys; home/.chezmoidata.yaml feeds ~/.gitconfig.
    ans, chez = load("group_vars/all.yml"), load("home/.chezmoidata.yaml")
    assert (chez["user_name"], chez["user_email"]) == (ans["user_name"], ans["user_email"])


def test_every_alias_has_name_and_cmd():
    for group in load("home/.chezmoidata.yaml")["alias_groups"]:
        for a in group["aliases"]:
            assert a.get("name") and a.get("cmd"), a
