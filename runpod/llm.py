#!/usr/bin/env python3
"""
llm — spin a RunPod GPU pod up/down for local (uncensored) LLM fiction writing,
with the model weights kept on a persistent RunPod *network volume*.

Thin wrapper over `runpodctl` (the official CLI, JSON output) + the Ollama HTTP
API. No Python dependencies — just python3 and runpodctl on your PATH.

Design
------
  Durable    : a RunPod network volume (created once) holds your Ollama models.
  Ephemeral  : the GPU pod, created on demand and DELETED when you're done.
               The volume — and every model on it — survives, so restarts are
               instant and you pay $0 for GPU while it's off.
  Frontend   : SillyTavern runs on YOUR laptop and connects to the pod's Ollama
               (a RunPod pod is a single container, so we don't run ST on it).

Daily workflow
--------------
  ./llm.py up                 # create the pod, print the Ollama URL for SillyTavern
  ./llm.py status             # is a pod running? which GPU?
  ./llm.py down               # DELETE the pod (models preserved on the volume, GPU -> $0)
  ./llm.py destroy            # DELETE everything incl. the volume -> truly $0 (models lost)

Model management (while a pod is up)
------------------------------------
  ./llm.py models             # list installed models + sizes + volume usage
  ./llm.py pull <model>       # add / upgrade a model, e.g. hermes3:70b
  ./llm.py rm <model>         # delete a model you no longer use (frees volume space)
  # upgrade without waste:  pull <new>  ->  try it  ->  rm <old>

Discovery / one-time setup
--------------------------
  ./llm.py gpus               # list GPU IDs + stock (use one as LLM_GPU)
  ./llm.py datacenters        # show which data centers have LLM_GPU in stock (--all for everything)
  ./llm.py create-volume      # create the volume (auto-picks an in-stock DC); copy id into LLM_VOLUME_ID

Config (environment — e.g. `source ../.env`)
--------------------------------------------
  RUNPOD_API_KEY    (required) runpodctl reads it from the env — `source .env` is enough to auth
  LLM_VOLUME_ID     (required for `up`)  output of create-volume
  LLM_GPU           default "NVIDIA A40"        (48GB, runs 70B Q4; cheapest 48GB card)
  LLM_MODEL         default "hermes3:70b"       (auto-pulled on first `up` if missing)
  LLM_DATACENTER    optional — create-volume auto-picks an in-stock DC for LLM_GPU if unset
  LLM_VOLUME_SIZE   default "80"  GB            (create-volume)
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

POD_NAME = "muse"
IMAGE = "ollama/ollama:latest"
OLLAMA_PORT = 11434
VOLUME_MOUNT = "/root/.ollama"  # ollama stores models here -> persisted on the volume
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pod-id")


# --- helpers -----------------------------------------------------------------

def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def env(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        die(f"{name} is not set (source your .env first)")
    return val


def read_pod_id():
    try:
        with open(STATE_FILE) as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def write_pod_id(pod_id):
    with open(STATE_FILE, "w") as f:
        f.write(pod_id)


def clear_pod_id():
    try:
        os.remove(STATE_FILE)
    except FileNotFoundError:
        pass


def runpodctl(cli_args, parse=True):
    """Run runpodctl (JSON output by default) -> parsed object, or raw text if parse=False."""
    try:
        out = subprocess.run(["runpodctl", *cli_args], capture_output=True, text=True, check=True)
    except FileNotFoundError:
        die("runpodctl not found — install it: curl -sSL https://cli.runpod.net | bash")
    except subprocess.CalledProcessError as e:
        die(f"`runpodctl {' '.join(cli_args)}` failed:\n{(e.stderr or e.stdout).strip()}")
    text = out.stdout.strip()
    if not parse:
        return text
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError:
        return text  # non-JSON output; caller decides what to do


def _find_id(obj):
    if isinstance(obj, dict):
        for k in ("id", "podId", "Id", "ID", "networkVolumeId"):
            if obj.get(k):
                return obj[k]
        # sometimes wrapped, e.g. {"pod": {...}} / {"networkVolume": {...}}
        for v in obj.values():
            found = _find_id(v) if isinstance(v, dict) else None
            if found:
                return found
    return None


def _pod_exists(pod_id):
    r = subprocess.run(["runpodctl", "pod", "get", pod_id], capture_output=True, text=True)
    return r.returncode == 0 and pod_id in r.stdout


def proxy_base(pod_id):
    # RunPod exposes an http port at https://<pod_id>-<port>.proxy.runpod.net
    return f"https://{pod_id}-{OLLAMA_PORT}.proxy.runpod.net"


def ollama_request(pod_id, path, method="GET", body=None, stream=False, timeout=60):
    url = proxy_base(pod_id) + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    resp = urllib.request.urlopen(req, timeout=timeout)
    return resp if stream else json.loads(resp.read().decode())


def human_size(num_bytes):
    n = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def require_running_pod():
    pod_id = read_pod_id()
    if not pod_id:
        die("no pod is up — run `./llm.py up` first")
    return pod_id


def wait_for_ollama(pod_id, timeout=480):
    print("waiting for Ollama to come online", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ollama_request(pod_id, "/api/tags", timeout=10)
            print(" ready.")
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError):
            print(".", end="", flush=True)
            time.sleep(8)
    print()
    return False


def _has_model(pod_id, model):
    try:
        data = ollama_request(pod_id, "/api/tags")
    except Exception:
        return False
    names = {m.get("name") for m in data.get("models", [])}
    return model in names or f"{model}:latest" in names


def _pull(pod_id, model):
    resp = ollama_request(pod_id, "/api/pull", method="POST",
                          body={"name": model}, stream=True, timeout=None)
    last = ""
    for raw in resp:
        line = raw.decode().strip()
        if not line:
            continue
        msg = json.loads(line)
        if "error" in msg:
            die(f"pull failed: {msg['error']}")
        status = msg.get("status", "")
        if msg.get("total") and "completed" in msg:
            line_out = f"  {status}: {100 * msg['completed'] / msg['total']:5.1f}%"
        else:
            line_out = f"  {status}"
        if line_out != last:
            print(line_out)
            last = line_out
    print(f"pulled {model}")


# --- commands ----------------------------------------------------------------

def cmd_up(args):
    if read_pod_id():
        die(f"a pod is already tracked ({read_pod_id()}); run `./llm.py down` first")

    gpu = args.gpu or env("LLM_GPU", "NVIDIA A40")
    volume_id = env("LLM_VOLUME_ID", required=True)
    model = env("LLM_MODEL", "hermes3:70b")

    # Guard: the volume is locked to one DC and the pod must run there. If LLM_GPU isn't in
    # stock in that DC, fail early with guidance instead of a raw RunPod error. (--force skips it.)
    if not args.force:
        dc_data = _dc_list()
        vdc = _volume_datacenter(volume_id, dc_data)
        if vdc and not _gpu_in_stock_at(dc_data, vdc, gpu):
            avail = _gpus_in_stock_at(dc_data, vdc)
            here = ", ".join(avail) if avail else "(nothing in stock right now)"
            die(f"'{gpu}' isn't in stock in your volume's data center ({vdc}) right now.\n"
                f"  GPUs in stock in {vdc}: {here}\n"
                f"Fix: set LLM_GPU to one of those, OR recreate the volume in a DC that has "
                f"'{gpu}' (`./llm.py datacenters --gpu \"{gpu}\"`), OR re-run `up --force` to try anyway.")

    print(f"creating pod '{POD_NAME}' on {gpu} (Secure Cloud); volume {volume_id} -> {VOLUME_MOUNT} ...")
    result = runpodctl([
        "pod", "create",
        "--name", POD_NAME,
        "--image", IMAGE,
        "--gpu-id", gpu,
        "--gpu-count", "1",
        "--cloud-type", "SECURE",            # network volumes require Secure Cloud
        "--network-volume-id", volume_id,
        "--volume-mount-path", VOLUME_MOUNT,
        "--container-disk-in-gb", "20",      # models live on the volume, not here
        "--ports", f"{OLLAMA_PORT}/http",
        "--env", json.dumps({"OLLAMA_HOST": "0.0.0.0"}),
    ])
    pod_id = _find_id(result)
    if not pod_id:
        die(f"couldn't parse a pod id from runpodctl output:\n{result}")
    write_pod_id(pod_id)
    print(f"pod {pod_id} created.")

    if not wait_for_ollama(pod_id):
        die("Ollama did not come online in time — check `./llm.py status` / the RunPod console")

    if model and not _has_model(pod_id, model):
        print(f"default model '{model}' not on the volume yet — pulling it ...")
        _pull(pod_id, model)

    base = proxy_base(pod_id)
    print("\n" + "=" * 64)
    print(f"  Ollama is up:  {base}")
    print(f"  SillyTavern (local) -> API type: Ollama, URL: {base}")
    print(f"  Done writing?  ./llm.py down   (GPU billing stops)")
    print("=" * 64)
    print("\nNOTE: that URL is publicly reachable while the pod runs (Ollama has no auth).")
    print("Keep the pod up only while writing. See README for SSH-tunnel hardening.")


def cmd_down(args):
    pod_id = read_pod_id()
    if not pod_id:
        print("no tracked pod — nothing to do.")
        return
    print(f"deleting pod {pod_id} (models stay on the volume) ...")
    runpodctl(["pod", "delete", pod_id], parse=False)
    clear_pod_id()
    print("done. GPU billing has stopped; you now pay only for the network volume.")
    print("Run `./llm.py destroy` to delete the volume too and reach $0.")


def cmd_status(args):
    pod_id = read_pod_id()
    if not pod_id:
        print("no pod is up.")
        return
    info = runpodctl(["pod", "get", pod_id])
    if isinstance(info, dict):
        status = info.get("desiredStatus") or info.get("status") or "?"
        machine = info.get("machine") if isinstance(info.get("machine"), dict) else {}
        gpu = machine.get("gpuDisplayName")
        print(f"pod {pod_id}: {status}" + (f" on {gpu}" if gpu else ""))
        print(f"  Ollama: {proxy_base(pod_id)}")
    else:
        print(info)


def cmd_models(args):
    pod_id = require_running_pod()
    data = ollama_request(pod_id, "/api/tags")
    models = data.get("models", [])
    if not models:
        print("no models installed. add one with `./llm.py pull <model>`")
        return
    total = 0
    print(f"{'MODEL':<32} {'SIZE':>10}")
    for m in sorted(models, key=lambda x: x.get("name", "")):
        size = m.get("size", 0)
        total += size
        print(f"{m.get('name',''):<32} {human_size(size):>10}")
    print("-" * 43)
    print(f"{'total':<32} {human_size(total):>10}  (network volume)")


def cmd_pull(args):
    pod_id = require_running_pod()
    print(f"pulling {args.model} (downloads onto the network volume) ...")
    _pull(pod_id, args.model)


def cmd_rm(args):
    pod_id = require_running_pod()
    ollama_request(pod_id, "/api/delete", method="DELETE", body={"name": args.model})
    print(f"removed {args.model} — volume space freed.")


def cmd_gpus(args):
    data = runpodctl(["gpu", "list"])
    items = data if isinstance(data, list) else data.get("gpus", []) if isinstance(data, dict) else None
    if not items:
        print(data)  # unknown shape — show raw so the user can still read it
        return
    print(f"{'GPU ID (use as LLM_GPU)':<44}{'VRAM':>6}  STOCK")
    for g in items:
        gid = g.get("id") or g.get("displayName") or ""
        mem = g.get("memoryInGb") or g.get("memory") or ""
        stock = g.get("stockStatus") or "-"
        print(f"{str(gid):<44}{(str(mem)+'GB') if mem else '':>6}  {stock}")


# Data centers that support network volumes. runpodctl exposes no field for this, so this list
# comes from the `network-volume create` error's "Available data centers" enumeration (2026-06).
# A GPU can be in stock in a DC that ISN'T here (e.g. CA-MTL-1) — you just can't put a volume there.
VOLUME_DCS = {
    "AP-JP-1", "CA-MTL-3", "CA-MTL-4", "EU-CZ-1", "EU-FR-1", "EU-NL-1", "EU-RO-1", "EU-SE-1",
    "EUR-IS-1", "EUR-IS-3", "EUR-NO-1", "EUR-NO-2", "US-CA-2", "US-GA-2", "US-IL-1", "US-KS-2",
    "US-MO-2", "US-NC-1", "US-NC-2", "US-NE-1", "US-TX-3", "US-WA-1",
}

_STOCK_RANK = {"high": 3, "medium": 2, "low": 1, "": 0}


def _stock_rank(status):
    return _STOCK_RANK.get((status or "").lower(), 0)


def _dc_list():
    data = runpodctl(["datacenter", "list"])
    if not isinstance(data, list):
        die(f"unexpected `datacenter list` output:\n{data}")
    return data


def _dcs_for_gpu(data, gpu, in_stock_only=True, volume_only=True):
    """[(dc_id, location, stock_label, rank)] for data centers offering `gpu`, best stock first.

    volume_only restricts to data centers that support network volumes (VOLUME_DCS)."""
    want = gpu.strip().lower()
    out = []
    for dc in data:
        if volume_only and dc.get("id") not in VOLUME_DCS:
            continue
        for g in dc.get("gpuAvailability") or []:
            gid = (g.get("gpuId") or "").lower()
            disp = (g.get("displayName") or "").lower()
            if want == gid or want == disp or want in gid:
                rank = _stock_rank(g.get("stockStatus"))
                if in_stock_only and rank == 0:
                    continue
                out.append((dc.get("id"), dc.get("location"), g.get("stockStatus") or "none", rank))
    out.sort(key=lambda x: -x[3])
    return out


def _in_stock_summary(data, volume_only=True):
    """{gpuId: ["DC(stock)", ...]} for every GPU with live stock in a volume-capable data center."""
    seen = {}
    for dc in data:
        if volume_only and dc.get("id") not in VOLUME_DCS:
            continue
        for g in dc.get("gpuAvailability") or []:
            if _stock_rank(g.get("stockStatus")) > 0:
                seen.setdefault(g.get("gpuId"), []).append(f"{dc.get('id')}({g.get('stockStatus')})")
    return seen


def _runpodctl_quiet(cli_args):
    """Run runpodctl without dying on error; return parsed JSON or None."""
    try:
        out = subprocess.run(["runpodctl", *cli_args], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout.strip())
    except json.JSONDecodeError:
        return None


def _volume_datacenter(volume_id, dc_data):
    """Best-effort data-center id a volume lives in. Schema-tolerant: finds whichever field
    holds a value matching a known DC id (runpodctl doesn't document the field name)."""
    vol = _runpodctl_quiet(["network-volume", "get", volume_id])
    if not isinstance(vol, dict):
        return None
    dc_ids = {dc.get("id") for dc in dc_data}

    def walk(o):
        if isinstance(o, str):
            return o if o in dc_ids else None
        if isinstance(o, dict):
            for v in o.values():
                hit = walk(v)
                if hit:
                    return hit
        return None

    return walk(vol)


def _dc_entry(dc_data, dc_id):
    for dc in dc_data:
        if dc.get("id") == dc_id:
            return dc
    return None


def _gpus_in_stock_at(dc_data, dc_id):
    dc = _dc_entry(dc_data, dc_id) or {}
    return [g.get("gpuId") for g in (dc.get("gpuAvailability") or [])
            if _stock_rank(g.get("stockStatus")) > 0]


def _gpu_in_stock_at(dc_data, dc_id, gpu):
    want = gpu.strip().lower()
    dc = _dc_entry(dc_data, dc_id) or {}
    for g in dc.get("gpuAvailability") or []:
        gid = (g.get("gpuId") or "").lower()
        disp = (g.get("displayName") or "").lower()
        if (want == gid or want == disp or want in gid) and _stock_rank(g.get("stockStatus")) > 0:
            return True
    return False


def cmd_datacenters(args):
    data = _dc_list()
    if args.all:
        for gid, locs in sorted(_in_stock_summary(data).items()):
            print(f"{gid:<44} {', '.join(locs)}")
        return
    gpu = args.gpu or env("LLM_GPU", "NVIDIA A40")
    matches = _dcs_for_gpu(data, gpu)
    if matches:
        print(f"data centers with '{gpu}' in stock that support network volumes (best first):\n")
        print(f"{'DATACENTER':<11}{'LOCATION':<18}STOCK")
        for dc_id, loc, stock, _ in matches:
            print(f"{str(dc_id):<11}{str(loc):<18}{stock}")
        print(f"\nrecommended:  export LLM_DATACENTER={matches[0][0]}")
        print("(or leave LLM_DATACENTER unset — `create-volume` auto-picks the best.)")
    else:
        print(f"no network-volume-capable data center currently has '{gpu}' in stock.\n")
        print("GPUs in stock in volume-capable data centers (set one as LLM_GPU, then re-run):\n")
        for gid, locs in sorted(_in_stock_summary(data).items()):
            print(f"  {gid:<44} {', '.join(locs)}")


def cmd_create_volume(args):
    name = "llm-models"
    size = env("LLM_VOLUME_SIZE", "80")
    gpu = env("LLM_GPU", "NVIDIA A40")
    dc = os.environ.get("LLM_DATACENTER")
    if not dc:
        matches = _dcs_for_gpu(_dc_list(), gpu)
        if not matches:
            die(f"LLM_DATACENTER is unset and no network-volume-capable data center currently has '{gpu}' in stock.\n"
                f"Run `./llm.py datacenters` to see what's available, then set LLM_GPU (and/or LLM_DATACENTER).")
        dc = matches[0][0]
        print(f"auto-selected data center {dc} ({matches[0][2]} stock for {gpu})")
    print(f"creating network volume '{name}' ({size}GB) in {dc} ...")
    result = runpodctl(["network-volume", "create",
                        "--name", name, "--size", str(size), "--data-center-id", dc])
    vid = _find_id(result) if isinstance(result, dict) else None
    if vid:
        print(f"\nvolume created: {vid}")
        print(f"add to your .env:   export LLM_VOLUME_ID={vid}")
    else:
        print(result)
        print("\nCopy the volume id above into LLM_VOLUME_ID in your .env")


def cmd_destroy(args):
    """Full teardown: delete the pod AND the volume -> truly $0 (models lost)."""
    volume_id = env("LLM_VOLUME_ID")

    print("This DELETES the pod AND the network volume.")
    print("All downloaded models are permanently lost; RunPod costs drop to $0.")
    if not args.yes:
        if not volume_id:
            die("LLM_VOLUME_ID is not set — nothing to delete (or use the RunPod console)")
        if input(f"Type the volume id ({volume_id}) to confirm: ").strip() != volume_id:
            die("confirmation did not match — aborted")

    # 1. delete the pod first (a volume can't be deleted while attached to a pod)
    pod_id = read_pod_id()
    if pod_id:
        print(f"deleting pod {pod_id} ...")
        runpodctl(["pod", "delete", pod_id], parse=False)
        clear_pod_id()
        for _ in range(15):  # wait for it to detach before deleting the volume
            if not _pod_exists(pod_id):
                break
            time.sleep(4)

    # 2. delete the volume
    if volume_id:
        print(f"deleting network volume {volume_id} ...")
        runpodctl(["network-volume", "delete", volume_id], parse=False)
        print("volume deleted.")
    else:
        print("no LLM_VOLUME_ID set — skipping volume delete (verify in the console).")

    print("\n✓ Everything destroyed. RunPod costs are now $0.")
    print("  Start fresh later with:  ./llm.py create-volume  then  ./llm.py up")


def main():
    p = argparse.ArgumentParser(description="RunPod GPU pod control for local LLM fiction writing")
    sub = p.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("up", help="create the GPU pod and bring Ollama online")
    up.add_argument("--gpu", help="override LLM_GPU for this run")
    up.add_argument("--force", action="store_true", help="skip the GPU-availability pre-check")
    up.set_defaults(func=cmd_up)

    sub.add_parser("down", help="delete the pod (models preserved on the volume)").set_defaults(func=cmd_down)
    sub.add_parser("status", help="show whether a pod is running").set_defaults(func=cmd_status)
    sub.add_parser("models", help="list installed models + sizes").set_defaults(func=cmd_models)

    pull = sub.add_parser("pull", help="add/upgrade a model (e.g. hermes3:70b)")
    pull.add_argument("model")
    pull.set_defaults(func=cmd_pull)

    rm = sub.add_parser("rm", help="delete a model to free volume space")
    rm.add_argument("model")
    rm.set_defaults(func=cmd_rm)

    sub.add_parser("gpus", help="list valid GPU IDs (for LLM_GPU)").set_defaults(func=cmd_gpus)
    dcs = sub.add_parser("datacenters", help="show where LLM_GPU is in stock (--all for everything)")
    dcs.add_argument("--gpu", help="GPU to look up (default: LLM_GPU)")
    dcs.add_argument("--all", action="store_true", help="list every in-stock GPU across data centers")
    dcs.set_defaults(func=cmd_datacenters)
    sub.add_parser("create-volume", help="one-time: create the persistent network volume").set_defaults(func=cmd_create_volume)

    destroy = sub.add_parser("destroy", help="DELETE everything (pod + volume) -> $0, models lost")
    destroy.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    destroy.set_defaults(func=cmd_destroy)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
