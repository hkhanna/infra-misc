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

files.put(
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
)
