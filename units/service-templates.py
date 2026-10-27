#!/usr/bin/env python3
"""Render the deliberately small native service templates."""
import json
import re
import sys


def replace(template, values):
    for key, value in values.items():
        template = template.replace("{{ " + key + " }}", value)
    if "{{" in template or "{%" in template:
        raise ValueError("unsupported or unexpanded service template expression")
    return template


def render_proxy(template, services):
    pattern = r"\{% for svc in web_services \| default\(\[\]\) %\}\n(.*?)\{% endfor %\}\n"
    match = re.search(pattern, template, re.DOTALL)
    if match is None or re.search(pattern, template[match.end():], re.DOTALL):
        raise ValueError("unsupported proxy service loop")
    if not isinstance(services, list):
        raise ValueError("web_services must be a list")
    body = match.group(1)
    key = "{{ svc.name | lower | replace(' ', '-') | replace('/', '-') }}"
    href = "{{ svc.href }}"
    if key not in body or href not in body:
        raise ValueError("unsupported proxy redirect template")
    sections = []
    for service in services:
        name, url = service["name"], service["href"]
        if not isinstance(name, str) or not isinstance(url, str):
            raise ValueError("service name and href must be strings")
        sections.append(body.replace(key, name.lower().replace(' ', '-').replace('/', '-')).replace(href, url))
    return replace(template[:match.start()] + ''.join(sections) + template[match.end():], {})


def main():
    mode, template_path, *args = sys.argv[1:]
    with open(template_path, encoding="utf-8") as source:
        template = source.read()
    if mode == "proxy":
        with open(args[0], encoding="utf-8") as source:
            rendered = render_proxy(template, json.load(source))
    elif mode == "dashboard":
        rendered = replace(template, {"bst_dashboard_dir": args[0], "bst_dashboard_image_name": args[1]})
    elif mode == "cert":
        rendered = replace(template, {"inventory_hostname": args[0], "tailscale_domain": args[1]})
    else:
        raise ValueError("unknown service template")
    sys.stdout.write(rendered)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
        print(f"service template: {error}", file=sys.stderr)
        sys.exit(1)
