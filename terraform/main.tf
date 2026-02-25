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

# resource "digitalocean_droplet" "this" {
#   name     = "abigail"
#   region   = "nyc3"
#   size     = "s-1vcpu-512mb-10gb"
#   image    = "debian-13-x64"
#   ssh_keys = [data.digitalocean_ssh_key.this.id]
# }

resource "digitalocean_spaces_bucket" "this" {
  name   = "khanna-s3"
  region = "nyc3"
  acl    = "public-read"
}

resource "digitalocean_domain" "do" {
  name = "do.khanna.law"
}

resource "digitalocean_record" "s3_cname" {
  domain = digitalocean_domain.do.id
  type   = "CNAME"
  name   = "s3"
  value  = "${digitalocean_cdn.spaces.endpoint}."
}

resource "digitalocean_certificate" "spaces" {
  name    = "spaces-cert"
  type    = "lets_encrypt"
  domains = ["s3.do.khanna.law"]
}

resource "digitalocean_cdn" "spaces" {
  origin           = digitalocean_spaces_bucket.this.bucket_domain_name
  custom_domain    = "s3.do.khanna.law"
  certificate_name = digitalocean_certificate.spaces.name
}

output "ipv4_address" {
  description = "Public IPv4 address of the droplet"
  value       = digitalocean_droplet.this.ipv4_address
}
