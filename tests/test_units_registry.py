import re
import tomllib

from conftest import REPO


def mise_units():
    tasks = tomllib.loads((REPO / "mise.toml").read_text())["tasks"]
    return {k.removeprefix("unit:"): v for k, v in tasks.items() if k.startswith("unit:")}


def wrapper():
    return (REPO / "scripts/run-units.sh").read_text()


def all_units():
    return set(re.search(r'^ALL_UNITS="([^"]*)"', wrapper(), re.M).group(1).split())


def test_every_unit_is_registered_everywhere():
    on_disk = {p.stem for p in (REPO / "units").glob("*.sh")} - {"lib"}
    assert set(mise_units()) == on_disk == all_units()


def test_mise_task_files_exist():
    for name, task in mise_units().items():
        assert task["file"] == f"units/{name}.sh"
        assert (REPO / task["file"]).is_file()


def test_tag_map_only_names_known_units():
    case = re.search(r"tasks_for_tag\(\) \{ case .*?esac; \}", wrapper(), re.S).group(0)
    named = set()
    for echoed in re.findall(r'echo "?([a-z0-9 -]+?)"? ?;;', case):
        named.update(echoed.split())
    assert named and named <= all_units()
