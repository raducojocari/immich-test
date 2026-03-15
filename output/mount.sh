#!/usr/bin/env bash
# mount.sh - Mounts the Unifi NAS over NFS at /Volumes/nas.

set -euo pipefail

NAS_HOST="192.168.1.253"
NAS_EXPORT="/volume/4f4177a8-2edb-471a-a967-45430316197c/.srv/.unifi-drive/drive/.data"
MOUNT_POINT="/Volumes/nas"

info()  { echo "[INFO]  $*"; }
error() { echo "[ERROR] $*" >&2; exit 1; }

# Re-invoke with sudo if not already running as root
if [[ "${EUID}" -ne 0 ]]; then
    exec sudo "$0" "$@"
fi

# Already mounted?
if mount | grep -q "${MOUNT_POINT}"; then
    info "NAS is already mounted at ${MOUNT_POINT}."
    exit 0
fi

# Check NAS is reachable (-t is the macOS timeout flag for ping)
ping -c 1 -t 2 "${NAS_HOST}" >/dev/null 2>&1 \
    || error "Cannot reach NAS at ${NAS_HOST}. Check that you are on the local network."

# Create mount point if needed
mkdir -p "${MOUNT_POINT}"

check_client_allowed() {
    local this_ip
    this_ip="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "unknown")"

    local allowed
    allowed="$(showmount -e "${NAS_HOST}" 2>/dev/null | grep "${NAS_EXPORT}" || true)"

    if [[ -n "${allowed}" && ! "${allowed}" =~ ${this_ip} ]]; then
        error "This machine (${this_ip}) is not in the NAS allowed clients list: ${allowed}
       Fix: add ${this_ip} to the NFS share permissions in the Unifi NAS admin UI."
    fi
}

check_client_allowed

info "Mounting ${NAS_HOST}:${NAS_EXPORT} at ${MOUNT_POINT}..."
mount -t nfs -o resvport "${NAS_HOST}:${NAS_EXPORT}" "${MOUNT_POINT}" \
    || error "Mount failed. Check NFS is enabled on the NAS and this machine has access."

info "NAS mounted successfully at ${MOUNT_POINT}."
