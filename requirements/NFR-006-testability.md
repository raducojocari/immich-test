# NFR-006 — Testability

| Field | Value |
|---|---|
| **ID** | NFR-006 |
| **Status** | Implemented |
| **Source** | CLAUDE.md project instructions |

## Description

The entire system must be verifiable by an automated test suite that runs without access to a live NAS, Docker daemon, or Immich server. Every new feature or bug fix must be accompanied by a corresponding automated test.

## Behaviour

- All external commands used by shell scripts (Docker, curl, mount, pgrep, etc.) and all file paths are injectable via environment variables. Tests substitute mock implementations without modifying the scripts under test.
- Shell script tests use a mock binary directory prepended to the system PATH. Mock binaries are lightweight shell scripts that simulate the behaviour of the real command (success, failure, specific output) for the scenario under test. No real system commands execute during tests.
- Python import tests use in-process mocking to substitute network calls, file system operations, and Immich API responses. No network connections are made during tests.
- The full test suite runs with a single command and reports a clear pass/fail result for every test case.
- Every error path, prerequisite check, and happy path has a corresponding test case.

## Acceptance Criteria

- Running `./tests/run_tests.sh` on a machine with no NAS, no Docker installed, and no running Immich server → all tests pass.
- Introducing a regression in any prerequisite check → at least one test fails and identifies the broken behaviour.
- A new functional feature is added → the change is only considered complete when accompanied by at least one automated test covering the new behaviour.
- The install script is covered by automated tests that verify all prerequisite checks and the happy path.

## Constraints

- Tests must not create, modify, or delete any real files outside of temporary directories that are cleaned up after each test.
- Tests must not make any real network connections.
- Tests must not require any credentials or secrets to run.
- Mock binaries and test fixtures are maintained alongside the scripts they test.

## Related Requirements

- All FR and NFR entries — every requirement must have corresponding test coverage.
- NFR-002 — Tests must pass on the system bash (bash 3.2) to validate compatibility.
