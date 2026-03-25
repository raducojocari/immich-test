# NFR-002 — macOS / Bash 3.2 Compatibility

| Field | Value |
|---|---|
| **ID** | NFR-002 |
| **Status** | Implemented |
| **Source** | Deployment constraint — macOS ships bash 3.2 |

## Description

All shell scripts must run correctly on the version of bash that ships with macOS (3.2), without requiring the user to install a newer shell. This ensures a zero-dependency setup experience on any Mac.

## Behaviour

- No bash 4+ syntax is used anywhere in the shell scripts.
- Specifically excluded: associative arrays (`declare -A`), uppercase/lowercase case modifiers (`${var^^}`, `${var,,}`), the `&>>` combined redirect operator, and any other syntax introduced after bash 3.2.
- Case conversion (e.g. uppercasing a profile name to construct an environment variable key) is performed using the portable `tr` utility.
- Temporary file and directory creation uses BSD-compatible `mktemp` patterns (trailing `X` characters only; no prefix extensions that differ between GNU and BSD implementations).

## Acceptance Criteria

- Every shell script passes a syntax check under bash 3.2: `bash --version | head -1` reports 3.2.x and `bash -n <script>` reports no errors.
- The full BATS test suite passes when executed with the system bash on macOS without installing bash via Homebrew.
- No use of `declare -A`, `${var^^}`, `${var,,}`, or `&>>` appears in any shell script.

## Constraints

- This requirement applies to all scripts under `output/` and `tests/`.
- The Python import script is not subject to this constraint (Python version compatibility is managed separately).

## Related Requirements

- NFR-006 — Tests must pass on the system bash to be meaningful compatibility evidence.
