# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repo provisions and hardens a DigitalOcean droplet ("abigail") using **Terraform** for infrastructure and **pyinfra** for server configuration. Remote state is stored in a DigitalOcean Spaces bucket (`khanna-tfstate`).

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
ssh root@$(terraform -chdir=terraform output -raw ipv4_address)
```

Python dependency management uses **uv** (`pyproject.toml` + `uv.lock`). Python >= 3.14 required.

## Architecture

- **`terraform/main.tf`** — Single-file Terraform config. Provisions: a droplet, a Spaces bucket with CDN + custom domain (`s3.do.khanna.law`), and a Let's Encrypt cert. S3-compatible backend for state (`nyc3.digitaloceanspaces.com`). Uses the `digitalocean` provider.
- **`pyinfra/inventory.py`** — Dynamically reads the droplet IP from Terraform output (via subprocess). No hardcoded IPs.
- **`pyinfra/deploy.py`** — Idempotent server hardening: apt updates, fail2ban, sshd hardening, unattended-upgrades, sysctl network hardening.
- **`pyinfra/templates/`** — Config file templates deployed to the droplet (sshd_config, auto-upgrades, sysctl hardening).
