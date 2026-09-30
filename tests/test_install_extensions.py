import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest import mock
import zipfile


SCRIPT = (
    Path(__file__).parents[1]
    / "roles"
    / "bluefin_common"
    / "files"
    / "install-extensions.py"
)


def load_installer():
    spec = importlib.util.spec_from_file_location("install_extensions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def extension_zip():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("metadata.json", "{}")
    return payload.getvalue()


class InstallExtensionsTests(unittest.TestCase):
    def setUp(self):
        self.module = load_installer()
        self.uuid = "example@example.com"
        self.responses = [
            Response(json.dumps({"extensions": [{"uuid": self.uuid, "pk": 1}]}).encode()),
            Response(json.dumps({"shell_version_map": {"47": {"pk": 2}}}).encode()),
            Response(extension_zip()),
        ]

    def run_installer(self, install_result=None):
        observed = {}

        def run(command, **_kwargs):
            if command[:2] == ["gnome-extensions", "info"]:
                return types.SimpleNamespace(returncode=1, stdout="", stderr="")
            if command[:2] == ["gnome-shell", "--version"]:
                return types.SimpleNamespace(returncode=0, stdout="GNOME Shell 47.0", stderr="")
            if command[:2] == ["gnome-extensions", "install"]:
                archive = command[-1]
                observed["archive"] = archive
                observed["mode"] = stat.S_IMODE(os.stat(archive).st_mode)
                if isinstance(install_result, Exception):
                    raise install_result
                return types.SimpleNamespace(
                    returncode=0 if install_result is None else install_result,
                    stdout="",
                    stderr="install failed",
                )
            raise AssertionError(f"unexpected command: {command}")

        with tempfile.TemporaryDirectory() as extension_dir:
            self.module.USER_EXT_DIR = extension_dir
            with mock.patch.object(
                self.module.urllib.request, "urlopen", side_effect=self.responses
            ), mock.patch.object(self.module.subprocess, "run", side_effect=run):
                self.module.install_ext(self.uuid)

        return observed

    def test_uses_owner_only_unique_archive_and_removes_it_after_success(self):
        observed = self.run_installer()

        self.assertNotEqual(observed["archive"], f"/tmp/{self.uuid}.zip")
        self.assertEqual(observed["mode"], 0o600)
        self.assertFalse(os.path.exists(observed["archive"]))

    def test_removes_archive_when_installer_raises(self):
        observed = self.run_installer(RuntimeError("installer crashed"))

        self.assertFalse(os.path.exists(observed["archive"]))


if __name__ == "__main__":
    unittest.main()
