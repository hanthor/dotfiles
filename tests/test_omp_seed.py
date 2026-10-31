import subprocess

from conftest import REPO, write_stub


def test_seed_does_not_change_vault_when_broker_is_unreachable(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "ssh", "exit 42\n")
    write_stub(bindir, "bw", 'touch "$HOME/bw-called"\nexit 0\n')
    result = subprocess.run(
        ["bash", str(REPO / "scripts/bw-seed-omp-broker.sh")],
        env={**env, "BW_SESSION": "test"}, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert not (tmp_path / "home/bw-called").exists()
