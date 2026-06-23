# RunPod GPU box for local fiction-writing LLMs

On-demand GPU for running uncensored open-weight models (via [Ollama](https://ollama.com))
with [SillyTavern](https://docs.sillytavern.app) as the writing frontend. Built around one
idea: **keep the durable thing (your models) and throw away the expensive thing (the GPU).**

```
┌─────────────────────────────┐         ┌──────────────────────────┐
│  Network volume (durable)   │◀──mount─│  GPU pod (ephemeral)     │
│  • Ollama model weights     │         │  • RTX A6000 48GB        │
│  • survives pod teardown    │         │  • runs ollama serve     │
│  • ~$0.07/GB/mo (only idle  │         │  • destroyed when done   │
│    cost; e.g. 80GB ≈ $5.6)  │         │  • $0 once destroyed     │
└─────────────────────────────┘         └──────────────────────────┘
                                          SillyTavern runs on YOUR laptop,
                                          pointed at the pod's Ollama URL.
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
- `python3` — that's the only other requirement (`llm.py` has **no Python dependencies**; it
  shells out to `runpodctl` and talks to Ollama's HTTP API).
- SillyTavern on your laptop (one-time): `git clone https://github.com/SillyTavern/SillyTavern && cd SillyTavern && ./start.sh` (or its Docker image).

## Config

Add to your `.env` (sourced before running):

```sh
export RUNPOD_API_KEY=...          # required
export LLM_VOLUME_ID=...           # required for `up` (from create-volume, below)
export LLM_GPU="NVIDIA A40"        # 48GB, runs 70B Q4 (default); see `./llm.py gpus`
export LLM_MODEL="hermes3:70b"     # auto-pulled on first `up` if missing (default)
export LLM_DATACENTER=             # optional — create-volume auto-picks an in-stock DC if unset
export LLM_VOLUME_SIZE="80"        # create-volume: GB
```

GPU options (set `LLM_GPU`): run `./llm.py gpus` for exact IDs. Good picks:

| `LLM_GPU` | VRAM | ~$/hr | Model tier |
|---|---|---|---|
| `NVIDIA A40` *(default)* | 48 GB | $0.44 | 70B Q4 — cheapest 48 GB, usually in stock |
| `NVIDIA L40S` | 48 GB | $0.86 | 70B Q4 — faster (Ada gen), widely in stock |
| `NVIDIA RTX A6000` | 48 GB | $0.49 | 70B Q4 — often out of stock |
| `NVIDIA RTX A5000` | 24 GB | $0.27 | 24–32B finetune; also drop `LLM_VOLUME_SIZE` to ~40 |
| `NVIDIA L4` | 24 GB | $0.39 | 24–32B, power-efficient |

Stock fluctuates — `./llm.py gpus` and `./llm.py datacenters` show **live** availability. The
A6000 and RTX 6000 Ada are frequently out of stock everywhere; A40 and L40S are usually available.

## One-time setup

```sh
source ../.env
./llm.py gpus                 # GPU IDs + live stock; set LLM_GPU (default: NVIDIA A40)
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
./llm.py up                   # ~1–2 min: create pod, bring Ollama online, print its URL
# -> in SillyTavern: API = Ollama, URL = the printed https://<id>-11434.proxy.runpod.net
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

**Upgrade without wasting space:** `pull <new>` → try it in SillyTavern → `rm <old>`.
The volume is a *fixed* provisioned size (you pay for the size, not how full it is), so size
it to your working set plus headroom to stage a replacement: 80 GB holds one 70B-Q4 (~42 GB)
plus room to download a second before pruning the first.

## Cost

- **Off (pod destroyed):** just the volume — 80 GB ≈ **$5.6/mo** (40 GB ≈ $2.8/mo). GPU = $0.
- **Writing:** the hourly GPU rate, per second. e.g. A6000 for 20 hrs/mo ≈ **$10**.
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

The Ollama URL (`https://<id>-11434.proxy.runpod.net`) is **publicly reachable while the pod
runs** and Ollama has no built-in auth. Because the pod is ephemeral and you keep it up only
while writing, the exposure window is small. To harden: deploy an image with `sshd`, expose
`22/tcp` with a public IP, and tunnel `ssh -L 11434:localhost:11434 ...` instead of using the
proxy — point SillyTavern at `http://localhost:11434`. (Future enhancement for this tool.)

## Status

Built on `runpodctl` v2.6 with flags verified against its live `--help`, but **not yet run
end-to-end against a live account** (a real `up` spends money). The likely spots to shake out
on the first run: the exact JSON field names in `pod create` / `network-volume create` output
(parsed leniently by `_find_id`), `pod get` status fields, and GPU/data-center availability in
your chosen region. If something's off, the error from `runpodctl` is surfaced verbatim.
