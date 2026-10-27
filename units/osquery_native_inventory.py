"""Resolve the connection variables used by the fleet collector, without Ansible."""
import json
from pathlib import Path
import re
import subprocess
import sys


FIELDS = ("ansible_host", "ansible_user", "ansible_ssh_user", "ansible_port",
          "ansible_ssh_port", "ansible_connection", "tailnet_name", "osquery_supported")
NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


def yaml_document(path):
    try:
        text = path.read_text(encoding="utf-8")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        result = subprocess.run(["yq", "-o=json", "-I=0", ".", str(path)],
                                capture_output=True, timeout=30, check=True)
        return json.loads(result.stdout)
    except FileNotFoundError as error:
        if error.filename == "yq":
            raise ValueError("native inventory requires yq for YAML") from None
        raise ValueError("inventory file cannot be read") from None
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        raise ValueError("inventory YAML could not be parsed") from None


def mapping(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("inventory contains malformed mappings")
    return value


def name_ok(name):
    if not isinstance(name, str) or not NAME.fullmatch(name) or name in (".", ".."):
        raise ValueError("inventory contains invalid names")
    return name


def variable_files(root, directory, name):
    base = root / directory
    for path in (base / name, base / (name + ".yml"), base / (name + ".yaml"), base / (name + ".json")):
        if path.is_file():
            yield path
        elif path.is_dir():
            for item in sorted(path.iterdir()):
                if item.is_file() and (item.suffix in ("", ".yml", ".yaml", ".json")) and not item.name.startswith("."):
                    yield item


def selected(values, fields):
    return {key: values[key] for key in fields if key in values}


def contains_template(value):
    if isinstance(value, str):
        return "{{" in value or "{%" in value
    if isinstance(value, dict):
        return any(contains_template(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_template(item) for item in value)
    return False


def load_inventory(path, resolve_vars=True, fields=FIELDS):
    path = Path(path)
    document = mapping(yaml_document(path))
    if not document:
        raise ValueError("inventory is empty")
    groups, hosts = {}, {}

    def group(name):
        name_ok(name)
        return groups.setdefault(name, {"hosts": set(), "children": set(), "vars": {}})

    def add_group(name, definition, depth=0):
        if depth > 100:
            raise ValueError("inventory contains a group cycle")
        entry = group(name)
        definition = mapping(definition)
        if set(definition) - {"hosts", "children", "vars"}:
            raise ValueError("inventory contains invalid group properties")
        entry["vars"].update(mapping(definition.get("vars")))
        for host, values in mapping(definition.get("hosts")).items():
            name_ok(host)
            entry["hosts"].add(host)
            hosts.setdefault(host, {}).update(mapping(values))
        for child, value in mapping(definition.get("children")).items():
            name_ok(child)
            entry["children"].add(child)
            add_group(child, value, depth + 1)

    group("all")
    for name, value in document.items():
        add_group(name, value)
        if name != "all":
            groups["all"]["children"].add(name)

    depths = {"all": 0}
    def visit(name, stack, depth):
        if name in stack:
            raise ValueError("inventory contains a group cycle")
        depths[name] = max(depth, depths.get(name, 0))
        for child in groups[name]["children"]:
            visit(child, stack | {name}, depth + 1)
    visit("all", set(), 0)

    def priority(name):
        value = groups[name]["vars"].get("ansible_group_priority", 1)
        if isinstance(value, bool):
            raise ValueError("invalid inventory group priority")
        try:
            return int(value)
        except (ValueError, TypeError):
            raise ValueError("invalid inventory group priority") from None

    order = sorted(groups, key=lambda g: (depths.get(g, 0), priority(g), g))
    members = {}
    def group_members(name):
        if name not in members:
            members[name] = set(groups[name]["hosts"])
            for child in groups[name]["children"]:
                members[name].update(group_members(child))
        return members[name]
    for name in order:
        group_members(name)
    result = {name: {"hosts": sorted(entry["hosts"]), "children": sorted(entry["children"])}
              for name, entry in groups.items()}
    if not resolve_vars:
        result["_meta"] = {"hostvars": {host: {} for host in hosts}}
        return result
    effective = {host: {} for host in hosts}
    # Inventory-defined group vars precede group_vars files; within each
    # source, parent groups precede children and siblings use priority/name.
    for name in order:
        for host in members[name]:
            effective[host].update(selected(groups[name]["vars"], fields))
    for name in order:
        variables = {}
        for source in variable_files(path.parent, "group_vars", name):
            variables.update(selected(mapping(yaml_document(source)), fields))
        for host in members[name]:
            effective[host].update(variables)
    for host in hosts:
        effective[host].update(selected(hosts[host], fields))
        for source in variable_files(path.parent, "host_vars", host):
            effective[host].update(selected(mapping(yaml_document(source)), fields))
        for value in effective[host].values():
            if contains_template(value):
                raise ValueError("inventory connection variables contain unresolved templates")
    # Group membership was already validated above.
    result["_meta"] = {"hostvars": effective}
    return result


def group_contains(inventory, group, host):
    item = inventory.get(group, {})
    return host in item.get("hosts", []) or any(
        group_contains(inventory, child, host) for child in item.get("children", []))


def main(argv):
    try:
        if len(argv) < 3 or argv[0] not in ("groups", "osquery-settings"):
            raise ValueError("invalid inventory query")
        host = argv[2]
        if argv[0] == "groups":
            if len(argv) < 4:
                raise ValueError("invalid inventory query")
            inventory = load_inventory(argv[1], resolve_vars=False)
            if host not in inventory["_meta"]["hostvars"]:
                raise ValueError("machine is absent from inventory")
            print(" ".join("true" if group_contains(inventory, group, host) else "false"
                           for group in argv[3:]))
        else:
            if len(argv) != 3:
                raise ValueError("invalid inventory query")
            booleans = ("skip_osquery", "osquery_supported", "osquery_poller_enabled")
            fields = booleans + ("osquery_version", "osquery_release_archives",
                                  "osquery_poller_path", "osquery_poller_state_dir")
            inventory = load_inventory(argv[1], fields=fields)
            if host not in inventory["_meta"]["hostvars"]:
                raise ValueError("machine is absent from inventory")
            values = inventory["_meta"]["hostvars"][host]
            for key in booleans:
                value = values.get(key)
                if value is None:
                    values[key] = None
                elif value is True or str(value).lower() in ("true", "yes", "on", "1"):
                    values[key] = True
                elif value is False or str(value).lower() in ("false", "no", "off", "0"):
                    values[key] = False
                else:
                    raise ValueError("invalid osquery boolean setting")
            for key in ("osquery_version", "osquery_poller_path", "osquery_poller_state_dir"):
                if key in values and not isinstance(values[key], str):
                    raise ValueError("invalid osquery string setting")
            if "osquery_release_archives" in values and not isinstance(values["osquery_release_archives"], dict):
                raise ValueError("invalid osquery release setting")
            print(json.dumps(values))
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"native inventory: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
