# NFR-008 — Security

| Field | Value |
|---|---|
| **ID** | NFR-008 |
| **Status** | Implemented |
| **Source** | Derived from credential handling and privileged operation requirements |

## Description

Credentials must never appear in version-controlled files, and operations requiring elevated privileges must be scoped to the minimum set of binaries required. This prevents accidental credential exposure and limits the blast radius of any compromised sudo configuration.

## Behaviour

- The Immich API key is stored only in a local credentials file (`.env.local`) that is excluded from version control. It is never written into any committed configuration file, script, or documentation.
- Passwordless `sudo` grants are limited to the specific binaries required for NAS operations: the system disk utility (for force-unmounting) and the NAS mount script. No other commands are granted elevated privileges.
- No other credentials, passwords, or secrets are hard-coded anywhere in the scripts or configuration files.
- Any script that requires a credential (API key) and does not find it configured exits immediately with a clear error message that tells the user where and how to set it, rather than proceeding with an empty or invalid value.

## Acceptance Criteria

- Scanning the git history for API key patterns (`git log --all -S <key-pattern>`) yields no results.
- The sudoers configuration allows only the two named binaries (disk utility and mount script); no wildcard or unrestricted root access is present.
- Running any script that requires an API key without the credentials file present → non-zero exit with a message directing the user to create the credentials file.
- The credentials file is listed in `.gitignore` and cannot be committed without explicitly overriding the ignore rule.

## Constraints

- The credentials file must be created manually by the user; no script creates it automatically or writes a default placeholder key into it.
- Sudo grants are installed by the `--setup` sub-command of the recovery agent; they are not present by default.

## Related Requirements

- FR-005 — The import requires an API key; its absence must produce a clear error.
- FR-006 — The recovery agent requires sudo for NAS operations; those grants must be scoped.
- FR-007 — User profiles extend credential handling to multiple API keys, all stored in the same credentials file.
