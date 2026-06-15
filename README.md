# infra-misc

Miscellaneous infrastructure managed with Terraform and configured with pyinfra. Provisions and hardens DigitalOcean droplets and runs Caddy-based domain redirects on them:

- **abigail** — redirects `abigailspannberger.com` → `hakeemjeffries.com` (302).
- **zulu** — general-purpose / "potpourri" droplet. Currently redirects `openprogress.us` → `opi.us` (301). Its running services are listed in a comment above the `digitalocean_droplet.zulu` resource in `terraform/main.tf`.

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.14
- [uv](https://docs.astral.sh/uv/)
- A [DigitalOcean API token](https://cloud.digitalocean.com/account/api/tokens) (read+write on `droplet`, `domain`, `certificate`, `cdn`; read on `ssh_key` — or Full Access)
- A [DigitalOcean Spaces access key](https://cloud.digitalocean.com/account/api/spaces) for state storage and the Spaces bucket
- An SSH key named `harry@eagle` in your DigitalOcean account
- A [SigNoz Cloud](https://signoz.io/) ingestion key + endpoint (pyinfra forwards Caddy logs there)

## Usage

```sh
# Copy env.example to .env and fill in your credentials
cp env.example .env
# edit .env with your credentials
source .env

cd terraform

# Initialize providers
terraform init

# Preview changes
terraform plan

# Apply
terraform apply
```

After applying, each droplet's public IP is printed as output (`abigail_ipv4_address`, `zulu_ipv4_address`).

## Configuring with pyinfra

Once the droplets are provisioned, configure and harden them with pyinfra. `inventory.py` reads each droplet's IP from Terraform output and defines one host per droplet (it also reads `SIGNOZ_ENDPOINT` / `SIGNOZ_INGESTION_KEY` from the environment, so `source .env` first):

```sh
source .env
cd pyinfra
uv run pyinfra inventory.py deploy.py
```

This is idempotent — safe to run again at any time. It will:

- Update system packages
- Install and enable fail2ban
- Harden sshd (key-only auth, no password login, limited auth tries)
- Enable automatic security updates (unattended-upgrades)
- Apply sysctl network hardening
- Install Caddy and deploy each host's redirect (source domain, target, and 301/302 are per-host data in `inventory.py`; Caddy auto-provisions Let's Encrypt TLS)
- Forward Caddy's JSON logs to SigNoz Cloud via an OpenTelemetry collector

SSH in with (swap the output name for the droplet you want):

```sh
ssh root@$(terraform -chdir=terraform output -raw abigail_ipv4_address)
ssh root@$(terraform -chdir=terraform output -raw zulu_ipv4_address)
```

## What gets created

| Resource | Description |
|----------|-------------|
| `digitalocean_droplet` (abigail, zulu) | 512MB / 1 vCPU droplets (Debian 13) in nyc3 — $4/mo each |
| `digitalocean_domain` + `digitalocean_record` | `abigailspannberger.com` and `openprogress.us` domains with `@` A records pointing at their droplets |
| `digitalocean_spaces_bucket` | `khanna-s3` bucket (nyc3) |
| `digitalocean_cdn` + `digitalocean_certificate` | CDN for the bucket on `s3.do.khanna.law` with a Let's Encrypt cert (plus the `do.khanna.law` domain / CNAME) |

Droplets are provisioned with the existing `harry@eagle` SSH key from your DigitalOcean account. Each redirect domain must have its nameservers pointed at DigitalOcean (`ns1/ns2/ns3.digitalocean.com`) for the A record and Caddy's TLS issuance to work.

Terraform state is stored remotely in the `khanna-tfstate` Spaces bucket (created manually, not managed by Terraform).

## Destroying

```sh
cd terraform
terraform destroy
```
