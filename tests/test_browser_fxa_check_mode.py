import json
from pathlib import Path

import pytest

from conftest import REPO, write_stub
from test_browser_fxa_unit import prepare, run


def configure_source(tmp_path, env, browser):
    root = tmp_path / "source"
    (root / "host_vars").mkdir(parents=True)
    (root / "units").mkdir()
    (root / "units/browser-fxa").symlink_to(REPO / "units/browser-fxa", target_is_directory=True)
    (root / "host_vars/himachal.yml").write_text(
        f'browser_fxa_browser: "{browser}"\nfxa_bw_username: "jreilly1821@gmail.com"\n'
    )
    env["DOTFILES_DIR"] = str(root)


def add_profile(base, name):
    profile = base / name
    profile.mkdir(parents=True)
    (base / "profiles.ini").write_text(
        f"[Profile0]\nIsRelative=1\nPath={name}\nDefault=1\n"
    )
    return profile


def snapshot(root):
    return {
        str(path.relative_to(root)): (
            path.lstat().st_mode & 0o777,
            path.read_bytes() if path.is_file() else None,
        )
        for path in root.rglob("*")
    }


@pytest.mark.parametrize("flatpak", [False, True])
def test_firefox_apply_selects_flatpak_first_then_native(stub_env, tmp_path, flatpak):
    env, home, _ = prepare(stub_env)
    env.pop("UNITS_CHECK", None)
    configure_source(tmp_path, env, "firefox")
    native = add_profile(home / ".mozilla/firefox", "native.default")
    selected = native
    if flatpak:
        selected = add_profile(home / ".var/app/org.mozilla.firefox/.mozilla/firefox", "flatpak.default")
    result = run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (selected / "signedInUser.json").read_text() == "session-data"
    if flatpak:
        assert not (native / "signedInUser.json").exists()
    assert (home / "signin-captured").read_text().splitlines()[0] == "jreilly1821@gmail.com"


def test_firefox_flatpak_does_not_fall_back_to_native(stub_env, tmp_path):
    env, home, _ = prepare(stub_env)
    env.pop("UNITS_CHECK", None)
    configure_source(tmp_path, env, "firefox-flatpak")
    native = add_profile(home / ".mozilla/firefox", "native.default")
    result = run(env)
    assert result.returncode == 0 and "profile not installed" in result.stdout
    assert not (native / "signedInUser.json").exists()
    assert not (home / "bw-calls").exists()


def prepare_check(stub_env, tmp_path):
    env, home, profile = prepare(stub_env)
    configure_source(tmp_path, env, "zen")
    env.update(UNITS_CHECK="1", CHECK_LOG=str(tmp_path / "check-calls"))
    write_stub(home / ".local/venvs/fxa/bin", "python", '''
if [ "$1" = -B ]; then
  [ "${PYFXA_ERROR:-0}" = 0 ] || exit 2
  echo "${PYFXA_STATE:-installed}"
else
  echo "unexpected python $*" >> "$CHECK_LOG"
  exit 1
fi
''')
    write_stub(Path(env["PATH"].split(":")[0]), "bw", 'echo "unexpected bw $*" >> "$CHECK_LOG"; exit 1\n')
    return env, home, profile


def test_check_reports_drift_without_mutation_or_secrets(stub_env, tmp_path):
    env, home, profile = prepare_check(stub_env, tmp_path)
    token = profile / "signedInUser.json"
    token.write_text(json.dumps({"accountData": {"verified": False, "sessionToken": "private-token"}}))
    token.chmod(0o644)
    before = snapshot(home)
    result = run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WOULD install Firefox Accounts sign-in script" in result.stdout
    assert "WOULD restrict Firefox Accounts token permissions" in result.stdout
    assert "data exists but is not verified; it will be left untouched" in result.stdout
    assert "WOULD attempt Firefox Accounts sign-in" not in result.stdout
    assert "private-token" not in result.stdout + result.stderr
    assert "s'ec ret" not in result.stdout + result.stderr
    assert snapshot(home) == before
    assert not Path(env["CHECK_LOG"]).exists()


def test_check_verified_profile_and_missing_dependencies(stub_env, tmp_path):
    env, home, profile = prepare_check(stub_env, tmp_path)
    (home / ".local/venvs/fxa/bin/python").unlink()
    dest = home / ".local/bin/fxa_signin.py"
    dest.parent.mkdir(parents=True)
    dest.write_bytes((REPO / "units/browser-fxa/fxa_signin.py").read_bytes())
    dest.chmod(0o700)
    token = profile / "signedInUser.json"
    token.write_text(json.dumps({"accountData": {"verified": True, "email": "secret@example.test"}}))
    token.chmod(0o600)
    before = snapshot(home)
    result = run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WOULD create Firefox Accounts venv and install PyFxA" in result.stdout
    assert "profile is verified" in result.stdout
    assert "WOULD attempt" not in result.stdout
    assert "secret@example.test" not in result.stdout + result.stderr
    assert snapshot(home) == before


def test_check_reports_inspection_errors_without_mutation(stub_env, tmp_path):
    env, home, profile = prepare_check(stub_env, tmp_path)
    env["PYFXA_ERROR"] = "1"
    before = snapshot(home)
    result = run(env)
    assert result.returncode != 0 and "inspect Firefox Accounts PyFxA" in result.stdout
    assert snapshot(home) == before
    env.pop("PYFXA_ERROR")
    (profile.parent / "profiles.ini").write_text("not an INI file")
    before = snapshot(home)
    result = run(env)
    assert result.returncode != 0 and "inspect Firefox Accounts default profile" in result.stdout
    assert snapshot(home) == before
    assert not Path(env["CHECK_LOG"]).exists()


def test_check_finds_native_firefox_profile(stub_env, tmp_path):
    env, home, _ = prepare_check(stub_env, tmp_path)
    configure_source_again = Path(env["DOTFILES_DIR"]) / "host_vars/himachal.yml"
    configure_source_again.write_text('browser_fxa_browser: "firefox"\n')
    profile = add_profile(home / ".mozilla/firefox", "native.default")
    before = snapshot(home)
    result = run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WOULD attempt Firefox Accounts sign-in" in result.stdout
    assert not (profile / "signedInUser.json").exists()
    assert snapshot(home) == before


def test_check_missing_pyfxa_and_unreadable_token(stub_env, tmp_path):
    env, home, profile = prepare_check(stub_env, tmp_path)
    env["PYFXA_STATE"] = "missing"
    before = snapshot(home)
    result = run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "WOULD install Firefox Accounts PyFxA" in result.stdout
    assert snapshot(home) == before
    (profile / "signedInUser.json").mkdir()
    before = snapshot(home)
    result = run(env)
    assert result.returncode != 0 and "FAIL  inspect Firefox Accounts token" in result.stdout
    assert snapshot(home) == before
    assert not Path(env["CHECK_LOG"]).exists()


def test_check_refuses_token_symlink(stub_env, tmp_path):
    env, home, profile = prepare_check(stub_env, tmp_path)
    target = home / "account-data"
    target.write_text("private")
    target.chmod(0o644)
    (profile / "signedInUser.json").symlink_to(target)
    before = snapshot(home)
    result = run(env)
    assert result.returncode != 0 and "token is a symlink" in result.stdout
    assert snapshot(home) == before
    assert not Path(env["CHECK_LOG"]).exists()
