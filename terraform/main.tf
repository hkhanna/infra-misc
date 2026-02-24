terraform {
  required_version = "~> 1.14"

  backend "s3" {
    endpoints = {
      s3 = "https://nyc3.digitaloceanspaces.com"
    }
    bucket = "khanna-tfstate"
    key    = "infra-misc/terraform.tfstate"
    region = "us-east-1"

    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
  }

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

provider "digitalocean" {
  token = var.do_token
}

variable "do_token" {
  description = "DigitalOcean API token"
  type        = string
  sensitive   = true
}

data "digitalocean_ssh_key" "this" {
  name = "harry@eagle"
}

resource "digitalocean_droplet" "this" {
  name     = "fun-redirects"
  region   = "nyc3"
  size     = "s-1vcpu-512mb-10gb"
  image    = "debian-13-x64"
  ssh_keys = [data.digitalocean_ssh_key.this.id]
}

output "ipv4_address" {
  description = "Public IPv4 address of the droplet"
  value       = digitalocean_droplet.this.ipv4_address
}
