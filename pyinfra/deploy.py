from pyinfra.operations import apt, files, server, systemd

# --- System updates ---

apt.update(
    name="Update apt cache",
    cache_time=3600,
)

apt.upgrade(
    name="Upgrade all packages",
)

# --- Install hardening packages ---

apt.packages(
    name="Install hardening packages",
    packages=["fail2ban", "unattended-upgrades"],
)

# --- SSH hardening ---

sshd_config = files.template(
    name="Deploy hardened sshd_config",
    src="templates/sshd_config.j2",
    dest="/etc/ssh/sshd_config",
    user="root",
    group="root",
    mode="644",
)

systemd.service(
    name="Restart sshd",
    service="ssh",
    restarted=True,
    _if=sshd_config.did_change,
)

# --- fail2ban ---

systemd.service(
    name="Enable and start fail2ban",
    service="fail2ban",
    running=True,
    enabled=True,
)

# --- Unattended upgrades ---

files.put(
    name="Configure unattended-upgrades",
    src="templates/20auto-upgrades",
    dest="/etc/apt/apt.conf.d/20auto-upgrades",
    user="root",
    group="root",
    mode="644",
)

# --- Sysctl hardening ---

sysctl_config = files.put(
    name="Deploy sysctl hardening config",
    src="templates/99-hardening.conf",
    dest="/etc/sysctl.d/99-hardening.conf",
    user="root",
    group="root",
    mode="644",
)

server.shell(
    name="Reload sysctl",
    commands=["sysctl --system"],
    _if=sysctl_config.did_change,
)

# --- OpenTelemetry Collector (log forwarding to SigNoz) ---

OTELCOL_VERSION = "0.146.1"

server.shell(
    name="Install otelcol-contrib",
    commands=[
        # Idempotent: skip the download/install if the target version is already present.
        f"otelcol-contrib --version 2>/dev/null | grep -q '{OTELCOL_VERSION}' || "
        f"(wget -q https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v{OTELCOL_VERSION}/otelcol-contrib_{OTELCOL_VERSION}_linux_amd64.deb -O /tmp/otelcol-contrib.deb && "
        "dpkg -i /tmp/otelcol-contrib.deb && rm /tmp/otelcol-contrib.deb)",
    ],
)

server.shell(
    name="Add otelcol-contrib user to systemd-journal group",
    commands=["usermod -aG systemd-journal otelcol-contrib"],
)

otelcol_config = files.template(
    name="Deploy otelcol-contrib config",
    src="templates/otelcol-config.yaml.j2",
    dest="/etc/otelcol-contrib/config.yaml",
    user="root",
    group="root",
    mode="644",
)

otelcol_env = files.template(
    name="Deploy otelcol-contrib environment file",
    src="templates/otelcol-contrib.conf.j2",
    dest="/etc/otelcol-contrib/otelcol-contrib.conf",
    user="root",
    group="root",
    mode="600",
)

systemd.service(
    name="Restart otelcol-contrib",
    service="otelcol-contrib",
    restarted=True,
    _if=lambda: otelcol_config.did_change() or otelcol_env.did_change(),
)

systemd.service(
    name="Enable and start otelcol-contrib",
    service="otelcol-contrib",
    running=True,
    enabled=True,
)

# --- Caddy reverse proxy (HTTPS redirect) ---

apt.packages(
    name="Install Caddy",
    packages=["caddy"],
)

caddyfile = files.template(
    name="Deploy Caddyfile",
    src="templates/Caddyfile.j2",
    dest="/etc/caddy/Caddyfile",
    user="root",
    group="root",
    mode="644",
)

systemd.service(
    name="Reload Caddy",
    service="caddy",
    reloaded=True,
    _if=caddyfile.did_change,
)

systemd.service(
    name="Enable and start Caddy",
    service="caddy",
    running=True,
    enabled=True,
)
