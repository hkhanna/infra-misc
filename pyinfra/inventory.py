import os
import subprocess

result = subprocess.run(
    ["terraform", "-chdir=../terraform", "output", "-raw", "ipv4_address"],
    capture_output=True,
    text=True,
    check=True,
)

abigail_ip = result.stdout.strip()

servers = [
    (abigail_ip, {
        "ssh_user": "root",
        "redirect_url": "https://hakeemjeffries.com",
        "signoz_endpoint": os.environ["SIGNOZ_ENDPOINT"],
        "signoz_ingestion_key": os.environ["SIGNOZ_INGESTION_KEY"],
    }),
]
