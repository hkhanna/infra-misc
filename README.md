# infra-misc

Miscellaneous infrastructure managed with Terraform. Currently provisions a DigitalOcean droplet.

## Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.14
- A [DigitalOcean API token](https://cloud.digitalocean.com/account/api/tokens)
- A [DigitalOcean Spaces access key](https://cloud.digitalocean.com/account/api/spaces) for state storage
- An SSH key named `harry@eagle` in your DigitalOcean account

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

After applying, the droplet's public IP is printed as output. SSH in with:

```sh
ssh root@$(terraform -chdir=terraform output -raw ipv4_address)
```

## What gets created

| Resource | Description |
|----------|-------------|
| `digitalocean_droplet` | 512MB / 1 vCPU droplet (Debian 13) in nyc3 — $4/mo |

The droplet is provisioned with the existing `harry@eagle` SSH key from your DigitalOcean account.

Terraform state is stored remotely in the `khanna-tfstate` Spaces bucket (created manually, not managed by Terraform).

## Destroying

```sh
cd terraform
terraform destroy
```
