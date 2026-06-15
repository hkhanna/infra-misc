# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repo provisions and hardens DigitalOcean droplets using **Terraform** for infrastructure and **pyinfra** for server configuration. Remote state is stored in a DigitalOcean Spaces bucket (`khanna-tfstate`).

Droplets:
- **abigail** — redirects `abigailspannberger.com` → `hakeemjeffries.com` (302).
- **zulu** — general-purpose / "potpourri" droplet for miscellaneous services. Its running services are listed in a comment above its `digitalocean_droplet.zulu` resource in `terraform/main.tf`. Currently: `openprogress.us` → `opi.us` (301 permanent redirect). Add new responsibilities to that comment as they're deployed.

Both droplets use the same Caddy-based redirect deploy (`pyinfra/deploy.py`); per-host details (source domain, redirect target, redirect type, hostname) are data-driven from `pyinfra/inventory.py`.

## Commands

All commands require `source .env` first (sets `TF_VAR_do_token`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`).

```sh
# Terraform
cd terraform
terraform init          # first time / provider updates
terraform plan          # preview changes
terraform apply         # provision infrastructure
terraform destroy       # tear down

# pyinfra (from repo root)
cd pyinfra
uv run pyinfra inventory.py deploy.py   # configure/harden the droplet (idempotent)

# SSH into the droplet
ssh root@$(terraform -chdir=terraform output -raw abigail_ipv4_address)
```

Python dependency management uses **uv** (`pyproject.toml` + `uv.lock`). Python >= 3.14 required.

## Architecture

- **`terraform/main.tf`** — Single-file Terraform config. Provisions: the droplets (abigail, zulu), their domains + A records, a Spaces bucket with CDN + custom domain (`s3.do.khanna.law`), and a Let's Encrypt cert. S3-compatible backend for state (`nyc3.digitaloceanspaces.com`). Uses the `digitalocean` provider.
- **`pyinfra/inventory.py`** — Dynamically reads each droplet's IP from Terraform output (via subprocess) and defines one server per droplet with its per-host redirect/hostname data. No hardcoded IPs.
- **`pyinfra/deploy.py`** — Idempotent server hardening: apt updates, fail2ban, sshd hardening, unattended-upgrades, sysctl network hardening.
- **`pyinfra/templates/`** — Config file templates deployed to the droplet (sshd_config, auto-upgrades, sysctl hardening).
