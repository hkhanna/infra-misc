terraform {
  required_version = "~> 1.14"

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
