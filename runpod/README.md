# RunPod GPU box for local fiction-writing LLMs

On-demand GPU for running uncensored open-weight models. The pod serves [Ollama](https://ollama.com);
you run the [Open WebUI](https://openwebui.com) chat box on your own Mac (one `docker run`, pointed at
the pod). Built around one idea: **keep the durable thing (your models) and throw away the expensive
thing (the GPU).**

```
  Network volume (durable)             GPU pod (ephemeral)
  ├─ Ollama model weights       mount  ├─ A100 80GB  (your LLM_GPU)
  └─ ~$0.07/GB/mo, survives teardown ▶ └─ runs Ollama; destroyed when done → $0

  Open WebUI runs on YOUR Mac (docker), pointed at the pod's Ollama URL → chat at localhost:3000.
```

There's **no powered-off-but-billed trap** like DigitalOcean: a destroyed pod costs nothing.
The only thing you pay while "off" is the network volume that holds your models.

## Why this instead of Terraform

The durable/ephemeral split makes Terraform's state model a liability (a reclaimed pod =
state drift), and the only RunPod TF provider is an unmaintained hobby project. This tool is
**stateless** — RunPod itself is the source of truth, queried live — and gives you on/off
*and* model-management in one command surface.

## Prerequisites

- A [RunPod](https://runpod.io) account + API key (Settings → API Keys).
- [`runpodctl`](https://docs.runpod.io/runpodctl) — the tool wraps it for all pod/volume ops:
  `curl -sSL https://cli.runpod.net | bash`. It reads `RUNPOD_API_KEY` from the environment, so once
  `.env` is sourced you're authenticated (no separate `runpodctl doctor` step needed).
- `python3` — `llm.py` has **no Python dependencies**; it shells out to `runpodctl` and talks to
  the pod's HTTP API.
- **Docker** on your Mac — to run the Open WebUI chat box locally (`up` prints the exact command).
  (No Docker? `pip install open-webui` then `OLLAMA_BASE_URL=<url> open-webui serve` also works.)

## Config

Add to your `.env` (sourced before running):

```sh
export RUNPOD_API_KEY=...          # required
export LLM_VOLUME_ID=...           # required for `up` (from create-volume, below)
export LLM_GPU="NVIDIA A100-SXM4-80GB"  # 80GB, reliably in stock (default); see `./llm.py gpus`
export LLM_MODEL="hermes3:70b"     # auto-pulled on first `up` if missing (default)
export LLM_DATACENTER=             # optional — create-volume auto-picks an in-stock DC if unset
export LLM_VOLUME_SIZE="80"        # create-volume: GB
```

GPU options (set `LLM_GPU`): run `./llm.py gpus` for exact IDs. Good picks:

| `LLM_GPU` | VRAM | ~$/hr | Notes |
|---|---|---|---|
| `NVIDIA A100-SXM4-80GB` *(default)* | 80 GB | $1.49 | runs 70B at Q5/Q6 or bigger; reliably in stock incl. US |
| `NVIDIA H100 80GB HBM3` | 80 GB | ~$2.4–2.9 | most widely in stock (~8 DCs), fastest |
| `NVIDIA A100 80GB PCIe` | 80 GB | $1.39 | slightly cheaper/slower A100 |
| `NVIDIA L40S` | 48 GB | $0.86 | 70B Q4; cheaper but availability spotty |
| `NVIDIA A40` | 48 GB | $0.44 | cheapest 48 GB; often only one volume-capable DC |
| `NVIDIA RTX A5000` | 24 GB | $0.27 | budget: 24–32B finetune; drop `LLM_VOLUME_SIZE` to ~40 |

Stock fluctuates and the cheap 48 GB cards (A40/L40S/A6000) are frequently unavailable in
**volume-capable** data centers — that's why the default is the 80 GB A100, which is reliably in
stock. `./llm.py gpus` and `./llm.py datacenters` show **live** availability.

## One-time setup

```sh
source ../.env
./llm.py gpus                 # GPU IDs + live stock; set LLM_GPU (default: NVIDIA A100-SXM4-80GB)
./llm.py datacenters          # (optional) where LLM_GPU is in stock right now
./llm.py create-volume        # auto-picks an in-stock DC for LLM_GPU; copy the id into LLM_VOLUME_ID
```

The volume is locked to its data center and the pod must run there, so `create-volume` only picks
a data center that **currently has `LLM_GPU` in stock** — you usually don't set `LLM_DATACENTER` at
all. If your chosen GPU is out of stock everywhere, `create-volume` stops and `./llm.py datacenters`
shows which GPUs *are* available so you can switch `LLM_GPU`.

## Daily workflow

```sh
source ../.env
./llm.py up                   # create pod + Ollama, pull the model, print the Ollama URL + a docker cmd
# -> run the printed `docker run ... open-webui` on your Mac, open http://localhost:3000, pick the model
# ...write...
./llm.py down                 # destroy the pod — models kept, GPU billing stops
```

`./llm.py status` shows whether a pod is up.

## Managing models (while a pod is up)

```sh
./llm.py models               # installed models + sizes + total volume usage
./llm.py pull hermes3:70b     # add or upgrade a model
./llm.py rm  old-model:tag    # delete one you don't use -> frees volume space
```

**Upgrade without wasting space:** `pull <new>` → try it in the UI → `rm <old>`. (You can also
pull/delete models from the Open WebUI UI: Settings → Admin Settings → Models.)
The volume is a *fixed* provisioned size (you pay for the size, not how full it is), so size
it to your working set plus headroom to stage a replacement: 80 GB holds one 70B-Q4 (~42 GB)
plus room to download a second before pruning the first.

## Cost

- **Off (pod destroyed):** just the volume — 80 GB ≈ **$5.6/mo** (40 GB ≈ $2.8/mo). GPU = $0.
- **Writing:** the hourly GPU rate, per second. e.g. A100 80GB for 20 hrs/mo ≈ **$30**.
- **Truly $0:** delete the volume too (`./llm.py destroy`) — nothing left to bill, models lost.

## Tear down completely

```sh
./llm.py down       # end a session: destroy the pod, KEEP models (volume still ≈ $5.6/mo)
./llm.py destroy    # nuke EVERYTHING: pod + volume -> $0, models permanently gone
```

`destroy` makes you retype the volume id to confirm (skip with `--yes`). It terminates the pod,
waits for it to detach, then runs `runpodctl network-volume delete <id>` — so RunPod has nothing
left to charge for. Start over later with `create-volume` + `up`.

## Security note

The pod's Ollama API (`https://<id>-11434.proxy.runpod.net`) is **publicly reachable while the pod
runs** and has no auth — anyone with the URL could use your GPU. The URL is unguessable (random pod
id) and the pod is ephemeral, so the window is small; just `down` when you're done. Open WebUI runs
on your Mac (localhost), so its login and chats never leave your machine. To fully close the API
exposure you'd tunnel over SSH instead of the proxy (needs an sshd image) — not implemented; the
ephemeral public URL is the current tradeoff.

## Status

Run live on `runpodctl` v2.6. Confirmed working: volume create + DC auto-pick, pod create, the
GPU-availability guard, and Ollama serving via the proxy (the RunPod/Cloudflare proxy 403s the
default `Python-urllib` User-Agent, so the tool sends a browser one). The bundled on-pod
`open-webui:ollama` image was tried and **abandoned** — it never booted on RunPod (container stuck,
`uptimeSeconds` 0 for 20+ min). Final design: the pod runs `ollama/ollama` (boots reliably) and
Open WebUI runs locally on your Mac, pointed at the pod's Ollama URL.
