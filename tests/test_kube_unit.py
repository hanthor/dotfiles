import stat
from pathlib import Path

import pytest

from conftest import write_stub
from unit_helpers import UNLOCKED_BW, calls, run_unit

NOTES = """\
if [ "$1 $2" = "get notes" ]; then
  case "$3" in
    kubeconfig) echo "home-kube"; exit 0 ;;
    talosconfig) echo "home-talos"; exit 0 ;;
    kubeconfig-aws-migration) echo "aws-kube"; exit 0 ;;
    talosconfig-aws-migration) exit 1 ;;
  esac
fi
"""


@pytest.fixture
def env(stub_env):
    bindir, env = stub_env
    write_stub(bindir, "bw", UNLOCKED_BW % NOTES)
    write_stub(bindir, "kubectl", 'echo "kubectl $*" >> "$HOME/calls"\n[ "$2" = get-clusters ] && printf "NAME\\nhome\\n"\nexit 0\n')
    env.update(BW_SESSION="x", DOTFILES_IS_DESKTOP="1")
    return env


def test_configs_are_written_private_and_the_home_cluster_is_pinned(env):
    r = run_unit("kube", env)
    assert r.returncode == 0, r.stdout + r.stderr
    home = Path(env["HOME"])
    assert (home / ".kube/config").read_text().strip() == "home-kube"
    assert (home / ".talos/config").read_text().strip() == "home-talos"
    assert (home / ".kube/config-aws-migration").read_text().strip() == "aws-kube"
    for f in (".kube/config", ".talos/config", ".kube/config-aws-migration"):
        assert stat.S_IMODE((home / f).stat().st_mode) == 0o600
    assert "kubectl config set-cluster home --tls-server-name=192.168.0.5" in calls(env)


def test_a_missing_note_warns_and_leaves_no_file(env):
    r = run_unit("kube", env)
    assert "AWS talosconfig missing in BW" in r.stdout
    assert not (Path(env["HOME"]) / ".talos/config-aws-migration").exists()


def test_locked_vault_leaves_existing_configs(env):
    cfg = Path(env["HOME"], ".kube/config")
    cfg.parent.mkdir()
    cfg.write_text("previous")
    r = run_unit("kube", env, STUB_UNLOCK_RC="1")
    assert r.returncode == 0 and "SKIPPED:" in r.stdout
    assert cfg.read_text() == "previous"


@pytest.mark.parametrize("extra", [{"DOTFILES_IS_DESKTOP": "0"}])
def test_non_desktops_do_nothing(env, extra):
    r = run_unit("kube", env, **extra)
    assert "SKIPPED:" in r.stdout
    assert not (Path(env["HOME"]) / ".kube").exists()


def test_skip_kube_host_var_wins_over_desktop(env, tmp_path):
    repo = tmp_path / "repo"
    (repo / "host_vars").mkdir(parents=True)
    (repo / "host_vars/phone.yml").write_text("machine_profile: cli-only\nskip_kube: true\n")
    (repo / "units").symlink_to(Path(__file__).resolve().parent.parent / "units")
    r = run_unit("kube", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="phone")
    assert "SKIPPED:" in r.stdout and not (Path(env["HOME"]) / ".kube").exists()
