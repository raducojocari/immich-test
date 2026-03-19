# Immich Self-Hosted Photo Library

Automated pipeline to migrate a Google Photos Takeout archive into a self-hosted [Immich](https://immich.app) instance, with cron-driven recovery.

---

## Getting Started

```bash
# One-time setup
sudo ./output/mount.sh                         # mount NAS at /Volumes/nas
./output/install.sh                            # download + configure Immich
echo "IMMICH_API_KEY=<key>" > output/.env.local  # API key for recover.sh
./output/recover.sh --setup                    # install cron (*/10 min) + sudoers (asks sudo once)

# First run (starts Docker + begins import; cron keeps it running automatically)
./output/recover.sh
```

---

## Commands

| Command | Description |
|---|---|
| `sudo ./output/mount.sh` | Mount NAS via NFS at `/Volumes/nas` |
| `./output/install.sh` | Download and configure Immich Docker stack |
| `./output/recover.sh --setup` | Install cron entry + sudoers for automated recovery |
| `./output/recover.sh` | Health-check; trigger full recovery if needed |
| `IMMICH_API_KEY=<key> python3 output/import.py --test` | Import 5 sample photos (verify setup) |
| `IMMICH_API_KEY=<key> python3 output/import.py --all` | Import all photos (resumable) |
| `IMMICH_API_KEY=<key> python3 output/import.py --failures` | Retry only previously failed files |
| `IMMICH_API_KEY=<key> python3 output/repair.py` | Re-trigger thumbnail generation for broken assets |
| `./output/start.sh` | Start Immich Docker stack manually |
| `./output/stop.sh` | Stop Immich Docker stack |
| `./output/reset.sh --confirm` | Wipe all uploaded data and start over |
| `./tests/run_tests.sh` | Run full test suite (BATS + pytest) |

---

## How It Works

- **`import.py`** — single-pass uploader. Reads Google Photos Takeout files from NAS, uploads to Immich via REST API. Writes `output/import.log` as a checkpoint; safe to kill and re-run.
- **`recover.sh`** — cron agent (runs every 10 min). Checks if the import is running and Immich is healthy. If not, performs full recovery: stops import → unmounts NAS → remounts → restarts Docker → waits for Immich → relaunches import.
- **Checkpoint**: `import.log` records every `CREATED`/`DUPLICATE` outcome. On restart, already-processed files are skipped in O(n) time.

See [ARCHITECTURE.md](ARCHITECTURE.md) for full system documentation and diagrams.

---

## Configuration

| File | Purpose |
|---|---|
| `output/.env.local` | `IMMICH_API_KEY=<key>` — sourced by `recover.sh` (gitignored) |
| `output/install/.env` | Immich config (paths, DB credentials) — written by `install.sh` |
| `output/install/docker-compose.override.yml` | Resource limits and NAS volume mount |

Key env vars for `import.py`: `IMMICH_PARALLEL` (default 10), `IMMICH_LARGE_MB` (default 99 MB), `IMMICH_TEST_COUNT` (default 5).

---

## Logs

| Log | Description |
|---|---|
| `output/logs/import.log` | Operational log — cleared on each import start |
| `output/logs/recover.log` | Recovery log — rolling, not cleared |
| `output/import.log` | Checkpoint log — persistent; records every file outcome |
