import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub


pytestmark = pytest.mark.skipif(shutil.which("just") is None, reason="just not installed")


@pytest.fixture
def apply_env(stub_env, tmp_path):
    _, env = stub_env
    home = Path(env["HOME"])
    bindir = home / ".local/bin"
    bindir.mkdir(parents=True)
    repo = home / ".local/share/dotfiles"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "online_hosts.py").write_text("")
    shutil.copyfile(REPO / "Justfile", repo / "Justfile")
    log = tmp_path / "calls"
    env.update(CALLS=str(log), BW_SESSION="stale")
    write_stub(bindir, "bw", '''
printf 'bw %s\n' "$*" >> "$CALLS"
case "$*" in
  'unlock --check') [ "${BW_SESSION:-}" = valid-session ] ;;
  sync) [ "${SYNC_FAIL:-0}" = 0 ] ;;
  *) exit 1 ;;
esac
''')
    write_stub(bindir, "git", 'exit 0\n')
    write_stub(bindir, "sudo", 'exit 0\n')
    write_stub(bindir, "ssh", 'printf "ssh\\n" >> "$CALLS"\n')
    write_stub(scripts, "bw-resolve.sh", '''
printf 'resolve\n' >> "$CALLS"
[ "${RESOLVE_FAIL:-0}" = 0 ] || exit 1
printf 'export BW_SESSION=valid-session\n'
''')
    write_stub(scripts, "run-units.sh", 'printf "units %s\\n" "$*" >> "$CALLS"\n')
    write_stub(scripts, "record-apply.py", 'exit 0\n')
    return env, repo, log


def run_apply(env, repo, *args):
    return subprocess.run(["just", "-f", str(repo / "Justfile"), *args], env=env, capture_output=True, text=True)


def test_secret_tag_validates_syncs_and_does_not_expose_session(apply_env):
    env, repo, log = apply_env
    result = run_apply(env, repo, "apply-tags", "omp,kube")
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert calls[:4] == ["bw unlock --check", "resolve", "bw unlock --check", "bw sync"]
    assert calls[4] == "units --tags omp,kube"
    assert "valid-session" not in result.stdout + result.stderr + "\n".join(calls)


def test_nonsecret_tag_does_not_prompt_or_sync(apply_env):
    env, repo, log = apply_env
    result = run_apply(env, repo, "apply-tags", "git")
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert calls == ["units --tags git"]


def test_remote_nonsecret_tag_does_not_resolve_vault(apply_env):
    env, repo, log = apply_env
    result = run_apply(env, repo, "apply-remote-tags", "phone", "git")
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == ["ssh"]


def test_failed_sync_runs_nonsecret_work_and_fails(apply_env):
    env, repo, log = apply_env
    env["SYNC_FAIL"] = "1"
    result = run_apply(env, repo, "apply-tags", "omp,kube")
    assert result.returncode != 0
    calls = log.read_text().splitlines()
    assert calls[-1] == "units --tags omp,kube --no-secrets"


def test_full_apply_skips_vault_units_when_unlock_fails(apply_env):
    env, repo, log = apply_env
    env["RESOLVE_FAIL"] = "1"
    result = run_apply(env, repo, "apply")
    assert result.returncode == 0, result.stderr
    calls = log.read_text().splitlines()
    assert calls[-1] == "units --no-secrets"


@pytest.mark.parametrize("drop_session", [False, True])
def test_remote_secret_apply_rejects_lost_ssh_session(apply_env, drop_session):
    env, repo, _ = apply_env
    bindir = Path(env["HOME"]) / ".local/bin"
    write_stub(repo / "scripts", "bw-resolve.sh", 'printf "sentinel-session"\n')
    write_stub(bindir, "ssh", '''
case "$*" in *sentinel-session*) exit 90 ;; esac
if [ "${DROP_SESSION:-0}" = 1 ]; then unset BW_SESSION; fi
exec bash -c "${!#}"
''')
    write_stub(bindir, "just", '''
[ "${BW_SESSION:-}" = sentinel-session ] || exit 91
touch "$HOME/remote-applied"
''')
    env["DROP_SESSION"] = "1" if drop_session else "0"
    result = subprocess.run(
        [shutil.which("just"), "-f", str(repo / "Justfile"), "apply-remote-tags", "phone", "omp"],
        env=env, capture_output=True, text=True,
    )
    assert (result.returncode == 0) is not drop_session
    assert (Path(env["HOME"]) / "remote-applied").exists() is not drop_session
    assert "sentinel-session" not in result.stdout + result.stderr
    if drop_session:
        assert "did not accept BW_SESSION" in result.stderr


@pytest.mark.parametrize("tag", ["shell", "dotfiles"])
def test_secret_bearing_aggregate_tags_resolve_locally(apply_env, tag):
    env, repo, log = apply_env
    result = run_apply(env, repo, "apply-tags", tag)
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [
        "bw unlock --check", "resolve", "bw unlock --check", "bw sync", f"units --tags {tag}"
    ]
    assert "valid-session" not in result.stdout + result.stderr


@pytest.mark.parametrize("tag", ["shell", "dotfiles"])
def test_secret_bearing_aggregate_tags_fail_closed_on_sync_error(apply_env, tag):
    env, repo, log = apply_env
    env["SYNC_FAIL"] = "1"
    result = run_apply(env, repo, "apply-tags", tag)
    assert result.returncode != 0
    assert log.read_text().splitlines()[-1] == f"units --tags {tag} --no-secrets"



@pytest.mark.parametrize("tag", ["shell", "dotfiles"])
def test_secret_bearing_aggregate_tags_resolve_remotely(apply_env, tag):
    env, repo, log = apply_env
    result = run_apply(env, repo, "apply-remote-tags", "phone", tag)
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == ["resolve", "ssh"]


@pytest.mark.parametrize("existing", ["insecure", "symlink", "directory"])
def test_remote_apply_cache_is_private_and_never_follows_symlinks(apply_env, tmp_path, existing):
    env, repo, _ = apply_env
    cache = tmp_path / "bw_session"
    target = tmp_path / "target"
    target.write_text("untouched")
    if existing == "insecure":
        cache.write_text("old")
        cache.chmod(0o666)
    elif existing == "symlink":
        cache.symlink_to(target)
    else:
        cache.mkdir()
    justfile = repo / "Justfile"
    justfile.write_text(justfile.read_text().replace("/tmp/bw_session", str(cache)).replace(
        r'dir=\"/tmp\"', f'dir=\\"{tmp_path}\\"'))
    bindir = Path(env["HOME"]) / ".local/bin"
    write_stub(repo / "scripts", "bw-resolve.sh", 'printf "sentinel-session"\n')
    write_stub(bindir, "ssh", '''
case "$*" in *sentinel-session*) exit 90 ;; esac
exec bash -c "${!#}"
''')
    write_stub(bindir, "just", '''
[ "$1" = push-terminfo ] && exit 0
[ "${BW_SESSION:-}" = sentinel-session ] || exit 91
touch "$HOME/remote-applied"
''')
    result = subprocess.run([shutil.which("just"), "-f", str(justfile), "apply-remote", "phone"],
                            cwd=repo, env=env, capture_output=True, text=True)
    assert (result.returncode != 0) is (existing == "directory")
    assert (Path(env["HOME"]) / "remote-applied").exists() is (existing != "directory")
    assert target.read_text() == "untouched"
    assert "sentinel-session" not in result.stdout + result.stderr
    if existing != "directory":
        assert not cache.is_symlink()
        assert cache.read_text() == "sentinel-session"
        assert cache.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".bw_session.*"))
