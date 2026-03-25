# Immich Self-Hosted Photo Library

Automated pipeline to migrate a Google Photos Takeout archive into a self-hosted [Immich](https://immich.app) instance, with cron-driven recovery.

---

## Getting Started

```bash
# One-time setup
sudo ./output/mount.sh                           # mount NAS at /Volumes/nas
./output/install.sh                              # download + configure Immich
echo "IMMICH_API_KEY=<key>" > output/.env.local  # API key for recover.sh
./output/recover.sh --setup                      # configure sudoers for NAS operations (asks sudo once)

# Start the recovery monitor (foreground loop; keep this terminal open)
./output/recover.sh
```

---

## Commands

| Command | Description |
|---|---|
| `sudo ./output/mount.sh` | Mount NAS via NFS at `/Volumes/nas` |
| `./output/install.sh` | Download and configure Immich Docker stack |
| `./output/recover.sh --setup` | Configure sudoers for NAS operations (run once) |
| `./output/recover.sh` | Start foreground recovery monitor (checks every 2 min) |
| `./output/recover.sh --once` | Run a single health check and exit |
| `IMMICH_API_KEY=<key> python3 output/import.py --test` | Import 5 sample photos (verify setup) |
| `IMMICH_API_KEY=<key> python3 output/import.py --all` | Import all photos (resumable) |
| `IMMICH_API_KEY=<key> python3 output/import.py --all --withvideo` | Import all videos (resumable) |
| `IMMICH_API_KEY=<key> python3 output/import.py --test --withvideo` | Import 5 sample videos (verify setup) |
| `IMMICH_API_KEY=<key> python3 output/import.py --failures` | Retry only previously failed files |
| `IMMICH_API_KEY=<key> python3 output/repair.py` | Re-trigger thumbnail generation for broken assets |
| `./output/start.sh` | Start Immich Docker stack manually |
| `./output/stop.sh` | Stop Immich Docker stack |
| `./output/reset.sh --confirm` | Wipe all uploaded data and start over |
| `./tests/run_tests.sh` | Run full test suite (BATS + pytest) |

---

## How It Works

- **`import.py`** — single-pass uploader. Reads Google Photos Takeout files from NAS, uploads to Immich via REST API. Writes `output/import.log` as a checkpoint; safe to kill and re-run.
- **`recover.sh`** — foreground recovery monitor (checks every 2 min). If import is running, Immich is healthy, NAS is mounted, and the checkpoint log is recent → skip. Any anomaly → full recovery: stops import → unmounts NAS → remounts → restarts Docker → waits for Immich → relaunches import.
- **Checkpoint**: `import.log` records every `CREATED`/`DUPLICATE` outcome. On restart, already-processed files are skipped in O(n) time.

See [ARCHITECTURE.md](ARCHITECTURE.md) for full system documentation and diagrams.

---

## Configuration

| File | Purpose |
|---|---|
| `output/.env.local` | `IMMICH_API_KEY=<key>` — sourced by `recover.sh` (gitignored) |
| `output/install/.env` | Immich config (paths, DB credentials) — written by `install.sh` |
| `output/install/docker-compose.override.yml` | Resource limits and NAS volume mount |

Key env vars for `import.py`: `IMMICH_PARALLEL` (default 10), `IMMICH_VIDEO_PARALLEL` (default 2), `IMMICH_LARGE_MB` (default 99 MB), `IMMICH_VIDEO_LARGE_MB` (default 4096 MB), `IMMICH_TEST_COUNT` (default 5). For `recover.sh`: `IMMICH_WITH_VIDEO=true` restarts the import in video mode after recovery (add to `.env.local`).

---

## Logs

| Log | Description |
|---|---|
| `output/logs/import.log` | Operational log — cleared on each import start |
| `output/logs/recover.log` | Recovery log — rolling, not cleared |
| `output/import.log` | Checkpoint log — persistent; records every file outcome |
