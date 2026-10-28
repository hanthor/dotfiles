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


@pytest.mark.parametrize("result", ["failure", "malformed", "invalid"])
def test_unknown_desktop_inventory_fails_without_reading_secrets(env, tmp_path, result):
    repo = tmp_path / "repo"
    (repo / "host_vars").mkdir(parents=True)
    (repo / "units").symlink_to(Path(__file__).resolve().parent.parent / "units")
    bindir = Path(env["PATH"].split(":")[0])
    write_stub(bindir, "yq", '''\
if [ "$LOOKUP" = failure ]; then exit 1; fi
case "$*" in
  *'| tag'*) [ "$LOOKUP" = malformed ] && echo '!!seq' || echo '!!map' ;;
  *) echo invalid ;;
esac
''')
    r = run_unit("kube", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="unknown",
                 DOTFILES_IS_DESKTOP="", LOOKUP=result)
    assert r.returncode != 0
    assert "FAIL" in r.stdout
    assert not (Path(env["HOME"]) / ".kube").exists()
    assert calls(env) == ""


@pytest.mark.parametrize("profile", ["skip_kube: true\n", "machine_profile: vm-test\n"])
def test_profile_skips_without_desktop_lookup(env, tmp_path, profile):
    repo = tmp_path / "repo"
    (repo / "host_vars").mkdir(parents=True)
    (repo / "host_vars/phone.yml").write_text(profile)
    (repo / "units").symlink_to(Path(__file__).resolve().parent.parent / "units")
    bindir = Path(env["PATH"].split(":")[0])
    write_stub(bindir, "yq", 'exit 1\n')
    r = run_unit("kube", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="phone",
                 DOTFILES_IS_DESKTOP="")
    assert r.returncode == 0 and "SKIPPED" in r.stdout
    assert calls(env) == ""


def test_failed_note_read_preserves_existing_config_even_with_stdout(env):
    cfg = Path(env["HOME"], ".kube/config")
    cfg.parent.mkdir()
    cfg.write_text("previous\n")
    bindir = Path(env["PATH"].split(":")[0])
    write_stub(bindir, "bw", UNLOCKED_BW % '''
if [ "$1 $2 $3" = "get notes kubeconfig" ]; then
  echo partial-private-config
  exit 1
fi
''')
    result = run_unit("kube", env)
    assert result.returncode == 0
    assert cfg.read_text() == "previous\n"
    assert "set-cluster" not in calls(env)
    assert "partial-private-config" not in result.stdout + result.stderr


def test_failed_cluster_listing_reports_failure_without_pinning_partial_output(env):
    bindir = Path(env["PATH"].split(":")[0])
    write_stub(bindir, "kubectl", '''
echo "kubectl $*" >> "$HOME/calls"
if [ "$2" = get-clusters ]; then printf 'NAME\\nhome\\n'; exit 1; fi
exit 0
''')
    result = run_unit("kube", env)
    assert result.returncode != 0 and "cannot list home kubeconfig clusters" in result.stdout
    assert "set-cluster" not in calls(env)
    assert Path(env["HOME"], ".kube/config-aws-migration").read_text().strip() == "aws-kube"


def test_missing_kubectl_reports_unpinned_config(env, tmp_path):
    bash_env = tmp_path / "bash-env"
    bash_env.write_text('''
command() {
  if [ "$1" = -v ] && [ "$2" = kubectl ]; then return 1; fi
  builtin command "$@"
}
''')
    result = run_unit("kube", env, BASH_ENV=str(bash_env))
    assert result.returncode != 0 and "kubectl missing; tls-server-name not pinned" in result.stdout
    assert Path(env["HOME"], ".kube/config-aws-migration").read_text().strip() == "aws-kube"
