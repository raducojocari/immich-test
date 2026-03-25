# FR-007 — User Profiles

| Field | Value |
|---|---|
| **ID** | FR-007 |
| **Status** | Planned |
| **Source** | User request — multi-user photo import |

## Description

The system must support multiple users importing from the same machine. Each user has their own Immich account (and therefore their own API key) and their own folder of source photos on the NAS. A profile name selects the correct credentials and source path for a given user without requiring any manual environment variable changes.

## Behaviour

- A profile is selected by passing a name keyword (e.g. `radu`, `roxana`) as a `--profile` argument.
- The profile name resolves two pieces of configuration from the local credentials file:
  - The API key for that user's Immich account.
  - The source photo directory for that user on the NAS.
- Each profile maintains its own independent import progress log. Progress for one user's import does not affect or skip files for another user's import.
- The recovery agent is profile-aware: when invoked for a specific profile it acquires a profile-specific concurrency lock, so two profiles can be recovered concurrently without blocking each other.
- If no profile is specified, the system falls back to the existing global API key and default source directory, preserving full backward compatibility.
- Profile names are case-insensitive.

## Acceptance Criteria

- `--profile radu` → uses Radu's API key and NAS source directory, writes to Radu's progress log.
- `--profile roxana` → uses Roxana's API key and NAS source directory, writes to Roxana's progress log.
- Profile API key not present in credentials file → exits 1, error message names the missing key.
- Profile source directory not present in credentials file → exits 1, error message names the missing key.
- Running recovery for `radu` and `roxana` simultaneously → both proceed independently without either waiting for the other.
- No `--profile` flag → existing behaviour unchanged; global API key and default source directory used.

## Constraints

- Profile configuration is stored in the existing local credentials file using a consistent prefix convention (`PROFILE_<NAME>_API_KEY`, `PROFILE_<NAME>_PHOTOS_DIR`). No additional configuration files are required.
- Profile names may only contain alphanumeric characters.
- The feature must not require changes to how Immich itself is configured or deployed.

## Related Requirements

- FR-005 — Photo import is the primary operation extended by user profiles.
- FR-006 — The recovery agent must be profile-aware to support concurrent multi-user recovery.
- NFR-001 — Each profile's progress log is independent, preserving per-user resumability.
- NFR-008 — All API keys remain in the local credentials file, never committed.
