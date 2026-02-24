# infra-misc

Miscellaneous infrastructure managed with Terraform. Currently provisions a DigitalOcean droplet.

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.14
- A [DigitalOcean API token](https://cloud.digitalocean.com/account/api/tokens)
- An SSH key named `harry@eagle` in your DigitalOcean account

## Usage

```sh
cd terraform

# Set your DO token (or you'll be prompted on each run)
# DO token is stored in 1Password (look for DO Token)
export TF_VAR_do_token="your-token-here"

# Initialize providers
terraform init

# Preview changes
terraform plan

# Apply
terraform apply
```

After applying, the droplet's public IP is printed as output. SSH in with:

```sh
ssh root@$(terraform -chdir=terraform output -raw ipv4_address)
```

## What gets created

| Resource | Description |
|----------|-------------|
| `digitalocean_droplet` | 512MB / 1 vCPU droplet (Debian 13) in nyc3 — $4/mo |

The droplet is provisioned with the existing `harry@eagle` SSH key from your DigitalOcean account.

## Destroying

```sh
cd terraform
terraform destroy
```
