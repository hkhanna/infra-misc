import os
import subprocess


def tf_output(name):
    result = subprocess.run(
        ["terraform", "-chdir=../terraform", "output", "-raw", name],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


signoz = {
    "signoz_endpoint": os.environ["SIGNOZ_ENDPOINT"],
    "signoz_ingestion_key": os.environ["SIGNOZ_INGESTION_KEY"],
}

servers = [
    (tf_output("abigail_ipv4_address"), {
        "ssh_user": "root",
        "hostname": "abigail",
        "redirect_domain": "abigailspannberger.com",
        "redirect_url": "https://hakeemjeffries.com",
        "redirect_permanent": False,
        **signoz,
    }),
    (tf_output("zulu_ipv4_address"), {
        "ssh_user": "root",
        "hostname": "zulu",
        "redirect_domain": "openprogress.us",
        "redirect_url": "https://opi.us",
        "redirect_permanent": True,
        **signoz,
    }),
]
