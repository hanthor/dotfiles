"""roles/browser_fxa/files/fxa_signin.py: profile discovery and signedInUser.json writing.

PyFxA is faked in sys.modules so no test touches the network, and the browser
base directories are pointed at tmp_path so nothing reads the real $HOME.
"""
import importlib.util
import json
import sys
import types

import pytest

from conftest import REPO

SCRIPT = REPO / "roles" / "browser_fxa" / "files" / "fxa_signin.py"


@pytest.fixture
def fxa(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("fxa_signin", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bases = {
        "zen": tmp_path / "zen",
        "firefox-flatpak": tmp_path / "flatpak",
        "firefox": tmp_path / "native",
    }
    for path in bases.values():
        path.mkdir()
    monkeypatch.setattr(mod, "BROWSER_BASES", {k: str(v) for k, v in bases.items()})
    for var in ("FXA_EMAIL", "FXA_PASSWORD", "FXA_TOTP", "BROWSER_TYPE", "PROFILE_DIR", "ZEN_PROFILE_DIR"):
        monkeypatch.delenv(var, raising=False)
    mod.bases = bases
    return mod


def write_ini(base, text):
    (base / "profiles.ini").write_text(text)


# --- find_default_profile -----------------------------------------------------

def test_install_section_default_wins_over_profile_flag(fxa, tmp_path):
    write_ini(tmp_path / "zen", (
        "[Profile0]\nName=old\nIsRelative=1\nPath=old.default\nDefault=1\n\n"
        "[Install4F96D1932A9F858E]\nDefault=Profiles/abc.release\nLocked=1\n"
    ))
    assert fxa.find_default_profile(str(tmp_path / "zen")) == str(tmp_path / "zen" / "Profiles/abc.release")


def test_relative_profile_flagged_default_is_joined_to_base(fxa, tmp_path):
    write_ini(tmp_path / "zen", (
        "[Profile0]\nName=other\nIsRelative=1\nPath=other\n\n"
        "[Profile1]\nName=main\nIsRelative=1\nPath=main.default\nDefault=1\n"
    ))
    assert fxa.find_default_profile(str(tmp_path / "zen")) == str(tmp_path / "zen" / "main.default")


def test_isrelative_defaults_to_relative_when_omitted(fxa, tmp_path):
    write_ini(tmp_path / "zen", "[Profile0]\nPath=main.default\nDefault=1\n")
    assert fxa.find_default_profile(str(tmp_path / "zen")) == str(tmp_path / "zen" / "main.default")


def test_absolute_profile_path_is_returned_as_is(fxa, tmp_path):
    write_ini(tmp_path / "zen", "[Profile0]\nIsRelative=0\nPath=/srv/profile\nDefault=1\n")
    assert fxa.find_default_profile(str(tmp_path / "zen")) == "/srv/profile"


def test_install_section_without_default_falls_back_to_profile_flag(fxa, tmp_path):
    write_ini(tmp_path / "zen", (
        "[Install1234]\nLocked=1\n\n"
        "[Profile0]\nPath=main.default\nDefault=1\n"
    ))
    assert fxa.find_default_profile(str(tmp_path / "zen")) == str(tmp_path / "zen" / "main.default")


def test_no_default_profile_raises(fxa, tmp_path):
    write_ini(tmp_path / "zen", "[Profile0]\nPath=main.default\nDefault=0\n")
    with pytest.raises(RuntimeError, match="Could not find default profile"):
        fxa.find_default_profile(str(tmp_path / "zen"))


def test_missing_profiles_ini_raises(fxa, tmp_path):
    with pytest.raises(RuntimeError, match="profiles.ini"):
        fxa.find_default_profile(str(tmp_path / "zen"))


# --- resolve_profile_dir ------------------------------------------------------

def test_profile_dir_env_overrides_detection(fxa, monkeypatch):
    monkeypatch.setenv("PROFILE_DIR", "/explicit")
    assert fxa.resolve_profile_dir() == "/explicit"


def test_legacy_zen_profile_dir_env_still_honoured(fxa, monkeypatch):
    monkeypatch.setenv("ZEN_PROFILE_DIR", "/legacy")
    assert fxa.resolve_profile_dir() == "/legacy"


def test_profile_dir_beats_legacy_zen_profile_dir(fxa, monkeypatch):
    monkeypatch.setenv("PROFILE_DIR", "/new")
    monkeypatch.setenv("ZEN_PROFILE_DIR", "/legacy")
    assert fxa.resolve_profile_dir() == "/new"


def test_zen_is_the_default_browser(fxa, tmp_path):
    write_ini(tmp_path / "zen", "[Profile0]\nPath=z\nDefault=1\n")
    assert fxa.resolve_profile_dir() == str(tmp_path / "zen" / "z")


def test_browser_type_is_case_insensitive(fxa, tmp_path, monkeypatch):
    write_ini(tmp_path / "flatpak", "[Profile0]\nPath=f\nDefault=1\n")
    monkeypatch.setenv("BROWSER_TYPE", "Firefox-Flatpak")
    assert fxa.resolve_profile_dir() == str(tmp_path / "flatpak" / "f")


def test_firefox_prefers_flatpak_over_native(fxa, tmp_path, monkeypatch):
    write_ini(tmp_path / "flatpak", "[Profile0]\nPath=f\nDefault=1\n")
    write_ini(tmp_path / "native", "[Profile0]\nPath=n\nDefault=1\n")
    monkeypatch.setenv("BROWSER_TYPE", "firefox")
    assert fxa.resolve_profile_dir() == str(tmp_path / "flatpak" / "f")


def test_firefox_falls_back_to_native(fxa, tmp_path, monkeypatch):
    write_ini(tmp_path / "native", "[Profile0]\nPath=n\nDefault=1\n")
    monkeypatch.setenv("BROWSER_TYPE", "firefox")
    assert fxa.resolve_profile_dir() == str(tmp_path / "native" / "n")


def test_firefox_without_any_profiles_ini_raises(fxa, monkeypatch):
    monkeypatch.setenv("BROWSER_TYPE", "firefox")
    with pytest.raises(RuntimeError, match="tried Flatpak and native"):
        fxa.resolve_profile_dir()


def test_unknown_browser_type_raises(fxa, monkeypatch):
    monkeypatch.setenv("BROWSER_TYPE", "netscape")
    with pytest.raises(RuntimeError, match="Unknown BROWSER_TYPE 'netscape'"):
        fxa.resolve_profile_dir()


# --- main ---------------------------------------------------------------------

class FakeSession:
    def __init__(self, token=b"\x01\xab", uid="uid-1", totp_ok=True):
        self.token, self.uid, self.totp_ok = token, uid, totp_ok
        self.totp_codes = []

    def totp_verify(self, code):
        self.totp_codes.append(code)
        return self.totp_ok


@pytest.fixture
def pyfxa(monkeypatch):
    """Install a fake `fxa.core`; returns a recorder of client constructions and logins."""
    rec = types.SimpleNamespace(urls=[], logins=[], session=FakeSession())

    class Client:
        def __init__(self, url):
            rec.urls.append(url)

        def login(self, email, password):
            rec.logins.append((email, password))
            return rec.session

    core = types.ModuleType("fxa.core")
    core.Client = Client
    pkg = types.ModuleType("fxa")
    pkg.core = core
    monkeypatch.setitem(sys.modules, "fxa", pkg)
    monkeypatch.setitem(sys.modules, "fxa.core", core)
    return rec


@pytest.fixture
def signed_in(fxa, tmp_path, monkeypatch):
    """Credentials set and PROFILE_DIR pointing at an empty profile; returns its signedInUser.json path."""
    profile = tmp_path / "profile"
    monkeypatch.setenv("FXA_EMAIL", "me@example.com")
    monkeypatch.setenv("FXA_PASSWORD", "hunter2")
    monkeypatch.setenv("PROFILE_DIR", str(profile))
    return profile / "signedInUser.json"


def run_main(fxa):
    with pytest.raises(SystemExit) as exc:
        fxa.main()
    return exc.value.code


@pytest.mark.parametrize("missing", ["FXA_EMAIL", "FXA_PASSWORD"])
def test_missing_credentials_exit_2(fxa, signed_in, monkeypatch, capsys, missing):
    monkeypatch.delenv(missing)
    assert run_main(fxa) == 2
    assert "FXA_EMAIL and FXA_PASSWORD must be set" in capsys.readouterr().err
    assert not signed_in.exists()


def test_unresolvable_profile_exits_4(fxa, signed_in, monkeypatch, capsys):
    monkeypatch.delenv("PROFILE_DIR")
    monkeypatch.setenv("BROWSER_TYPE", "netscape")
    assert run_main(fxa) == 4
    assert "Unknown BROWSER_TYPE" in capsys.readouterr().err


def test_already_verified_exits_0_without_touching_pyfxa(fxa, signed_in, monkeypatch, capsys):
    signed_in.parent.mkdir()
    original = json.dumps({"accountData": {"email": "old@example.com", "verified": True}})
    signed_in.write_text(original)
    monkeypatch.setitem(sys.modules, "fxa", None)  # any import of PyFxA would raise
    assert run_main(fxa) == 0
    assert "Already signed in as old@example.com" in capsys.readouterr().err
    assert signed_in.read_text() == original


def test_unverified_existing_file_is_replaced(fxa, signed_in, pyfxa):
    signed_in.parent.mkdir()
    signed_in.write_text(json.dumps({"accountData": {"email": "old@example.com", "verified": False}}))
    fxa.main()
    assert json.loads(signed_in.read_text())["accountData"]["email"] == "me@example.com"


def test_malformed_existing_file_is_overwritten(fxa, signed_in, pyfxa):
    signed_in.parent.mkdir()
    signed_in.write_text("{not json")
    fxa.main()
    assert json.loads(signed_in.read_text())["accountData"]["verified"] is True


def test_missing_pyfxa_exits_3(fxa, signed_in, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "fxa", None)
    assert run_main(fxa) == 3
    assert "PyFxA not installed" in capsys.readouterr().err
    assert not signed_in.exists()


def test_successful_login_writes_signed_in_user(fxa, signed_in, pyfxa, capsys):
    fxa.main()
    assert pyfxa.urls == ["https://api.accounts.firefox.com"]
    assert pyfxa.logins == [("me@example.com", "hunter2")]
    assert json.loads(signed_in.read_text()) == {
        "version": 1,
        "accountData": {
            "email": "me@example.com",
            "sessionToken": "01ab",  # bytes token is hex-encoded
            "uid": "uid-1",
            "verified": True,
        },
    }
    out = capsys.readouterr()
    assert "Wrote signedInUser.json for me@example.com" in out.out
    assert "hunter2" not in out.out + out.err


def test_string_token_is_stored_unchanged(fxa, signed_in, pyfxa):
    pyfxa.session = FakeSession(token="already-a-string")
    fxa.main()
    assert json.loads(signed_in.read_text())["accountData"]["sessionToken"] == "already-a-string"


def test_profile_directory_is_created(fxa, signed_in, pyfxa):
    assert not signed_in.parent.exists()
    fxa.main()
    assert signed_in.exists()


def test_totp_code_is_stripped_and_verified(fxa, signed_in, pyfxa, monkeypatch):
    monkeypatch.setenv("FXA_TOTP", " 123456\n")
    fxa.main()
    assert pyfxa.session.totp_codes == ["123456"]


def test_totp_skipped_when_not_supplied(fxa, signed_in, pyfxa):
    fxa.main()
    assert pyfxa.session.totp_codes == []


def test_blank_totp_is_treated_as_not_supplied(fxa, signed_in, pyfxa, monkeypatch):
    monkeypatch.setenv("FXA_TOTP", "   ")
    fxa.main()
    assert pyfxa.session.totp_codes == []


def test_failed_totp_exits_1_and_writes_nothing(fxa, signed_in, pyfxa, monkeypatch, capsys):
    pyfxa.session = FakeSession(totp_ok=False)
    monkeypatch.setenv("FXA_TOTP", "000000")
    assert run_main(fxa) == 1
    assert "TOTP verification failed" in capsys.readouterr().err
    assert not signed_in.exists()
