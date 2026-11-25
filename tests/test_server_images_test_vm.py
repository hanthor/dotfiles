"""server-images/test-vm.py: identity/bootc checks, guest scripts, switch-starter proof and CLI.

The script drives QEMU through pexpect, so none of that runs here. The pure
helpers are called directly, `VM` is replaced by a scripted fake to walk
`switch_starter` end to end, and the shell the guest would execute is syntax
checked with `bash -n`.
"""
import importlib.util
import json
import re
import subprocess
import sys
import types

import pytest

from conftest import REPO

SCRIPT = REPO / "server-images" / "test-vm.py"

IMAGE = "registry.example.com/home/starter:switch"
DIGEST = "sha256:" + "a" * 64
OLD_REF = "registry.example.com/home/starter:installed"
OLD_DIGEST = "sha256:" + "b" * 64


def load():
    # CI installs only pytest and pyyaml; the module imports pexpect at top level.
    if "pexpect" not in sys.modules:
        try:
            import pexpect  # noqa: F401
        except ImportError:
            sys.modules["pexpect"] = types.ModuleType("pexpect")
    spec = importlib.util.spec_from_file_location("server_images_test_vm", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def vm_mod():
    return load()


def machine_id(char="1"):
    return char * 32


def identity(char="1"):
    return {"machine_id": machine_id(char), "iqn": f"InitiatorName=iqn.2024-01.test:{char}"}


def bootc(booted=(OLD_REF, OLD_DIGEST), staged=None):
    def entry(pair):
        if pair is None:
            return None
        ref, digest = pair
        return {"image": {"image": {"transport": "registry", "image": ref}, "imageDigest": digest}}

    return {"status": {"booted": entry(booted), "staged": entry(staged)}}


# --- assert_identity -------------------------------------------------------

def test_assert_identity_accepts_valid(vm_mod):
    vm_mod.assert_identity(identity())


@pytest.mark.parametrize("bad", ["", "0" * 32, "1" * 31, "1" * 33, "G" * 32, "A" * 32])
def test_assert_identity_rejects_bad_machine_id(vm_mod, bad):
    with pytest.raises(RuntimeError, match="machine identity"):
        vm_mod.assert_identity({"machine_id": bad, "iqn": "InitiatorName=iqn.x"})


def test_assert_identity_rejects_non_iscsi_iqn(vm_mod):
    with pytest.raises(RuntimeError, match="iSCSI identity"):
        vm_mod.assert_identity({"machine_id": machine_id(), "iqn": "iqn.2024-01.test:1"})


# --- assert_distinct_identities --------------------------------------------

def write_identity(path, node, char):
    (path / f"{node}-identity.json").write_text(json.dumps(identity(char)))


def test_distinct_identities_pass_for_present_nodes(vm_mod, tmp_path):
    write_identity(tmp_path, "starter", "1")
    write_identity(tmp_path, "bihar", "2")
    vm_mod.assert_distinct_identities(tmp_path)


def test_distinct_identities_ignore_missing_unrequired_files(vm_mod, tmp_path):
    vm_mod.assert_distinct_identities(tmp_path)


def test_distinct_identities_require_named_node(vm_mod, tmp_path):
    with pytest.raises(FileNotFoundError):
        vm_mod.assert_distinct_identities(tmp_path, required=("karnataka",))


def test_distinct_identities_reject_cloned_machine_id(vm_mod, tmp_path):
    write_identity(tmp_path, "bihar", "3")
    write_identity(tmp_path, "karnataka", "3")
    with pytest.raises(RuntimeError, match="Cloned installed node identity: machine_id"):
        vm_mod.assert_distinct_identities(tmp_path)


def test_distinct_identities_reject_cloned_iqn_only(vm_mod, tmp_path):
    (tmp_path / "bihar-identity.json").write_text(json.dumps(identity("4")))
    other = identity("5")
    other["iqn"] = identity("4")["iqn"]
    (tmp_path / "karnataka-identity.json").write_text(json.dumps(other))
    with pytest.raises(RuntimeError, match="Cloned installed node identity: iqn"):
        vm_mod.assert_distinct_identities(tmp_path)


def test_distinct_identities_validate_each_file(vm_mod, tmp_path):
    (tmp_path / "starter-identity.json").write_text(json.dumps({"machine_id": "0" * 32, "iqn": "InitiatorName=iqn.x"}))
    with pytest.raises(RuntimeError, match="machine identity"):
        vm_mod.assert_distinct_identities(tmp_path)


# --- bootc_image -----------------------------------------------------------

def test_bootc_image_returns_reference_and_digest(vm_mod):
    assert vm_mod.bootc_image(bootc(), "booted") == (OLD_REF, OLD_DIGEST)


@pytest.mark.parametrize("deployment", ["staged", "rollback"])
def test_bootc_image_missing_deployment(vm_mod, deployment):
    with pytest.raises(RuntimeError, match=f"Missing {deployment} bootc image"):
        vm_mod.bootc_image(bootc(), deployment)


def test_bootc_image_entry_without_image(vm_mod):
    with pytest.raises(RuntimeError, match="Missing booted bootc image"):
        vm_mod.bootc_image({"status": {"booted": {"image": None}}}, "booted")


def test_bootc_image_rejects_non_registry_transport(vm_mod):
    status = bootc()
    status["status"]["booted"]["image"]["image"]["transport"] = "oci"
    with pytest.raises(RuntimeError, match="Unexpected booted bootc transport"):
        vm_mod.bootc_image(status, "booted")


# --- section ---------------------------------------------------------------

def test_section_extracts_marked_block(vm_mod):
    output = "noise\nSTATE_BEGIN\n{\"a\": 1}\nSTATE_END\ntrailer"
    assert vm_mod.section(output, "STATE") == '{"a": 1}'


def test_section_keeps_multiline_body_and_picks_the_right_marker(vm_mod):
    output = "BOOTC_BEGIN\nline1\nline2\nBOOTC_END\nSTATE_BEGIN\nx\nSTATE_END"
    assert vm_mod.section(output, "BOOTC") == "line1\nline2"
    assert vm_mod.section(output, "STATE") == "x"


def test_section_missing_reports_output_tail(vm_mod):
    with pytest.raises(RuntimeError, match="Missing guest proof section STATE:\nonly this"):
        vm_mod.section("only this", "STATE")


def test_section_requires_marker_at_line_start(vm_mod):
    with pytest.raises(RuntimeError, match="Missing guest proof section"):
        vm_mod.section("xSTATE_BEGIN\nbody\nSTATE_END", "STATE")


# --- guest shell -----------------------------------------------------------

GUEST_SCRIPTS = ["inactive_k3s", "starter_readiness", "switch_state_script"]


@pytest.mark.parametrize("name", GUEST_SCRIPTS)
def test_guest_script_is_valid_bash(vm_mod, name):
    result = subprocess.run(["bash", "-n"], input=getattr(vm_mod, name)(), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ["starter_readiness", "switch_state_script"])
def test_embedded_python_heredocs_compile(vm_mod, name):
    script = getattr(vm_mod, name)()
    blocks = re.findall(r"python3 - <<'PY'\n(.*?)\nPY\n", script, re.S)
    assert blocks, "expected an embedded python heredoc"
    for block in blocks:
        compile(block, f"<{name}>", "exec")


def test_switch_state_script_emits_both_parseable_sections(vm_mod):
    script = vm_mod.switch_state_script()
    for marker in ("BOOTC", "STATE"):
        assert script.index(f"{marker}_BEGIN") < script.index(f"{marker}_END")
    # The shell's printf writes a real newline before each marker: section() needs the marker at line start.
    assert "printf '\\nSTATE_BEGIN\\n'" in script


def test_switch_state_script_embeds_inactive_k3s_checks(vm_mod):
    assert vm_mod.inactive_k3s() in vm_mod.switch_state_script()


# --- switch_starter with a scripted VM -------------------------------------

class FakeVM:
    """Stand-in for VM that replays canned guest output and records what ran."""

    instances = []
    outputs = []
    scripts = []
    calls = []

    def __init__(self, args, node, **kwargs):
        self.node = node
        self.kwargs = kwargs
        FakeVM.instances.append(self)

    def root_login(self):
        FakeVM.calls.append("root_login")

    def run(self, script, timeout=None):
        FakeVM.scripts.append((script, timeout))
        return FakeVM.outputs.pop(0)

    def reboot(self):
        FakeVM.calls.append("reboot")

    def poweroff(self):
        FakeVM.calls.append("poweroff")

    def close(self):
        FakeVM.calls.append("close")


def guest_output(**sections):
    return "".join(f"\n{name}_BEGIN\n{json.dumps(body)}\n{name}_END\n" for name, body in sections.items())


SENTINEL = "f" * 64


def state(boot_id="boot-1", sentinel=SENTINEL, hostname="starter-smoke", **overrides):
    value = {
        "boot_id": boot_id,
        "hostname": hostname,
        "sentinel": sentinel,
        **identity(),
        "admin": {"name": "nodeadmin", "uid": 1000, "gid": 1000, "home": "/var/home/nodeadmin",
                  "shell": "/bin/bash", "groups": ["nodeadmin", "wheel"]},
    }
    value.update(overrides)
    return value


@pytest.fixture
def switch(vm_mod, tmp_path, monkeypatch):
    """Returns run(**overrides) -> args; FakeVM replaces VM and the sentinel token is fixed."""
    FakeVM.instances, FakeVM.outputs, FakeVM.scripts, FakeVM.calls = [], [], [], []
    monkeypatch.setattr(vm_mod, "VM", FakeVM)
    monkeypatch.setattr(vm_mod.secrets, "token_hex", lambda n: SENTINEL)
    (tmp_path / "starter-bootc.json").write_text(json.dumps(bootc()))
    (tmp_path / "starter-identity.json").write_text(json.dumps(identity()))

    def run(before=None, staged=None, after=None, before_status=None, after_status=None, **arg_overrides):
        FakeVM.outputs[:] = [
            guest_output(STATE=before if before is not None else state(),
                         BOOTC=before_status or bootc()),
            guest_output(BOOTC=staged or bootc(staged=(IMAGE, DIGEST))),
            guest_output(STATE=after if after is not None else state(boot_id="boot-2"),
                         BOOTC=after_status or bootc(booted=(IMAGE, DIGEST))),
        ]
        args = types.SimpleNamespace(artifacts=tmp_path, image=IMAGE, expected_digest=DIGEST,
                                     insecure_registry=None, accel="tcg")
        vars(args).update(arg_overrides)
        vm_mod.switch_starter(args)
        return args

    return run


def test_switch_starter_success_writes_proof(switch, tmp_path, capsys):
    switch()
    proof = json.loads((tmp_path / "starter-switch-proof.txt").read_text())
    assert proof["marker"] == "STARTER_SWITCH_PASSED"
    assert proof["image"] == IMAGE and proof["expected_digest"] == DIGEST
    assert proof["booted_ref"] == IMAGE and proof["booted_digest"] == DIGEST
    assert proof["previous_ref"] == OLD_REF
    assert proof["hostname"] == "starter-smoke"
    assert all(proof["checks"].values())
    assert "STARTER_SWITCH_PASSED" in capsys.readouterr().out
    # Two VM sessions (before/after reboot); each is closed and the node powers off once.
    assert FakeVM.calls == ["root_login", "reboot", "close", "root_login", "poweroff", "close"]
    assert all(vm.kwargs == {"outbound": True} for vm in FakeVM.instances)


def test_switch_starter_plants_sentinel_and_runs_bootc_switch(switch):
    switch()
    first, second, third = (s for s, _ in FakeVM.scripts)
    assert SENTINEL in first
    assert f"bootc switch {IMAGE}" in second
    assert FakeVM.scripts[1][1] == 1800
    assert "registries.conf.d" not in second
    assert "99-home-k8s-switch-smoke.conf" in third  # asserted absent after the reboot


def test_switch_starter_insecure_registry_fixture(switch):
    image = "localhost:5000/starter:switch"
    switch(image=image, insecure_registry="localhost:5000",
           staged=bootc(staged=(image, DIGEST)), after_status=bootc(booted=(image, DIGEST)))
    second = FakeVM.scripts[1][0]
    assert 'location = "localhost:5000"' in second and "insecure = true" in second
    assert "trap 'rm -f /etc/containers/registries.conf.d/99-home-k8s-switch-smoke.conf' EXIT" in second
    assert second.index("insecure = true") < second.index("bootc switch")


@pytest.mark.parametrize("authority", ["http://localhost:5000", "*.example.com", "-bad", "host:port", "a b"])
def test_switch_starter_rejects_malformed_insecure_registry(switch, authority):
    with pytest.raises(RuntimeError, match="exact host"):
        switch(insecure_registry=authority)
    assert FakeVM.instances == []


def test_switch_starter_insecure_registry_must_match_image_host(switch):
    with pytest.raises(RuntimeError, match="exactly match the target image registry"):
        switch(insecure_registry="other.example.com")
    assert FakeVM.instances == []


def test_switch_starter_needs_prior_install_artifacts(switch, tmp_path):
    (tmp_path / "starter-identity.json").unlink()
    with pytest.raises(FileNotFoundError):
        switch()
    assert FakeVM.instances == []


def test_switch_starter_rejects_unexpected_starting_deployment(switch):
    with pytest.raises(RuntimeError, match="actually TUI-installed starter"):
        switch(before_status=bootc(booted=("registry.example.com/other:tag", OLD_DIGEST)))
    assert FakeVM.calls[-1] == "close"


def test_switch_starter_rejects_preexisting_staged_deployment(switch):
    with pytest.raises(RuntimeError, match="already has a staged deployment"):
        switch(before_status=bootc(staged=(IMAGE, DIGEST)))


@pytest.mark.parametrize("key", ["machine_id", "iqn"])
def test_switch_starter_rejects_identity_changed_since_install(switch, key):
    with pytest.raises(RuntimeError, match=f"installed identity changed before switch: {key}"):
        switch(before=state(**{key: "changed"}))


def test_switch_starter_rejects_wrong_sentinel(switch):
    with pytest.raises(RuntimeError, match="Invalid starter sentinel"):
        switch(before=state(sentinel="not-the-sentinel"))


def test_switch_starter_rejects_root_admin(switch):
    admin = state()["admin"] | {"uid": 0}
    with pytest.raises(RuntimeError, match="Invalid starter sentinel or local administrator"):
        switch(before=state(admin=admin))


def test_switch_starter_rejects_replaced_booted_deployment_before_reboot(switch):
    with pytest.raises(RuntimeError, match="replaced the booted deployment before reboot"):
        switch(staged=bootc(booted=(IMAGE, DIGEST), staged=(IMAGE, DIGEST)))


def test_switch_starter_rejects_staged_digest_mismatch(switch):
    with pytest.raises(RuntimeError, match="exact reference and digest"):
        switch(staged=bootc(staged=(IMAGE, "sha256:" + "c" * 64)))
    assert "reboot" not in FakeVM.calls


def test_switch_starter_rejects_missing_staged_deployment(switch):
    with pytest.raises(RuntimeError, match="Missing staged bootc image"):
        switch(staged=bootc())


def test_switch_starter_rejects_unchanged_boot_after_reboot(switch, tmp_path):
    with pytest.raises(RuntimeError, match="did not boot the exact switched image"):
        switch(after_status=bootc())
    assert not (tmp_path / "starter-switch-proof.txt").exists()


def test_switch_starter_rejects_still_staged_after_reboot(switch):
    with pytest.raises(RuntimeError, match="still staged after reboot"):
        switch(after_status=bootc(booted=(IMAGE, DIGEST), staged=(IMAGE, DIGEST)))


def test_switch_starter_rejects_same_boot_id(switch):
    with pytest.raises(RuntimeError, match="did not observe a new kernel boot"):
        switch(after=state(boot_id="boot-1"))


@pytest.mark.parametrize("key,value", [
    ("hostname", "bihar"),
    ("sentinel", "gone"),
    ("machine_id", machine_id("9")),
    ("iqn", "InitiatorName=iqn.new"),
    ("admin", {"name": "nodeadmin", "uid": 1001}),
])
def test_switch_starter_rejects_lost_persistent_state(switch, tmp_path, key, value):
    with pytest.raises(RuntimeError, match=f"lost persistent starter state: {key}"):
        switch(after=state(boot_id="boot-2", **{key: value}))
    assert not (tmp_path / "starter-switch-proof.txt").exists()


# --- main() argument handling ----------------------------------------------

@pytest.fixture
def cli(vm_mod, tmp_path, monkeypatch):
    seen = []
    for name in ("install", "switch_starter", "cluster"):
        monkeypatch.setattr(vm_mod, name, lambda args, name=name: seen.append((name, args)))

    def run(*argv, kvm=True):
        monkeypatch.setattr(sys, "argv", ["test-vm.py", "--artifacts", str(tmp_path / "out"), *argv])
        monkeypatch.setattr(vm_mod.os, "access", lambda *a: kvm)
        vm_mod.main()
        return seen

    return run


SWITCH = ["--accel", "tcg", "switch-starter", "--image", IMAGE, "--expected-digest", DIGEST]


def test_main_dispatches_each_command(cli):
    assert cli("--accel", "tcg", "install", "bihar")[-1][0] == "install"
    assert cli("--accel", "tcg", "cluster")[-1][0] == "cluster"
    assert cli(*SWITCH)[-1][0] == "switch_starter"


def test_main_resolves_and_creates_artifacts_dir(cli, tmp_path):
    name, args = cli("--accel", "tcg", "cluster")[-1]
    assert args.artifacts == (tmp_path / "out").resolve()
    assert args.artifacts.is_dir()


def test_main_rejects_unknown_install_node(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        cli("--accel", "tcg", "install", "laptop")
    assert exc.value.code == 2


@pytest.mark.parametrize("digest", ["sha256:abc", "a" * 64, "sha256:" + "A" * 64, "sha256:" + "a" * 65, ""])
def test_main_rejects_malformed_digest(cli, capsys, digest):
    with pytest.raises(SystemExit) as exc:
        cli("--accel", "tcg", "switch-starter", "--image", IMAGE, "--expected-digest", digest)
    assert exc.value.code == 2
    assert "sha256 manifest digest" in capsys.readouterr().err


@pytest.mark.parametrize("image", ["noslash", "-registry.io/x", "reg.io/has space", "reg.io/tab\tx"])
def test_main_rejects_malformed_image(cli, capsys, image):
    with pytest.raises(SystemExit) as exc:
        cli("--accel", "tcg", "switch-starter", f"--image={image}", "--expected-digest", DIGEST)
    assert exc.value.code == 2
    assert "fully qualified registry image" in capsys.readouterr().err


def test_main_requires_kvm_unless_tcg(cli, capsys):
    with pytest.raises(SystemExit) as exc:
        cli("cluster", kvm=False)
    assert exc.value.code == 2
    assert "/dev/kvm is unavailable" in capsys.readouterr().err
    # Explicit TCG does not need /dev/kvm.
    assert cli("--accel", "tcg", "cluster", kvm=False)[-1][0] == "cluster"
