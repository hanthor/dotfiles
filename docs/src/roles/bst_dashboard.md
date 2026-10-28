# bst_dashboard

`units/bst-dashboard.sh` renders `units/bst-dashboard/bst-dashboard.service.j2` with `units/service-templates.py`, installs the resulting user service, reloads the user manager when changed, and enables and starts it. A changed service definition is started or restarted after the reload so the running dashboard uses the new configuration; a permissions-only change does not restart it. It also enables user linger via root or noninteractive `sudo -n`. It does not install the dashboard project or retrieve secrets.

The unit skips retired `matrix` and `telengana`, and skips when the project directory is missing. On `karnataka` it selects `/var/home/james/dev/kde-linux` and image `aurora`; elsewhere it selects `/var/home/james/dev/dakota` and image `dakota`. Access is through the Caddy `/bst/` route when that proxy is configured.
