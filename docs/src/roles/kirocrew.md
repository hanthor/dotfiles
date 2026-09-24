# kirocrew

Keeps the [Kiro Crew](https://github.com/kirodotdev/KiroCrew) gateway
(dashboard + Slack + cron) healthy on hosts that run it — currently punjab.

- **Enable**: `kirocrew_enabled: true` in `host_vars/<host>.yml`
- **Tags**: `services`, `kirocrew`

The venv (`~/.kiro/crew-venv`) and the systemd unit are owned by Kiro's own
installer (`kirocrew service install`), so the role does **not** template them.
It:

1. warns if the binary or unit is missing (install per upstream first),
2. keeps `/etc/kirocrew/kirocrew.env` `root:root 0600` — tokens go there,
3. enables and starts `kirocrew.service`,
4. fails the play if the dashboard listens on anything but localhost.
