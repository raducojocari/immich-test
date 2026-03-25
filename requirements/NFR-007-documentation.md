# NFR-007 — Documentation

| Field | Value |
|---|---|
| **ID** | NFR-007 |
| **Status** | Implemented |
| **Source** | CLAUDE.md project instructions |

## Description

The project must be fully documented so that any new user or future maintainer can understand the system, get it running, and make changes without prior knowledge of the codebase. Documentation must be kept in sync with the implementation.

## Behaviour

- A README file contains a Getting Started section that shows how to go from a fresh machine to a running Immich instance and active import with a single command. Additional commands (start, stop, reset, etc.) are documented concisely.
- An architecture document describes the overall system design, its components, and the relationships between them. It includes at least one system overview diagram and sequence diagrams covering the key workflows (installation, import, recovery).
- All diagrams are written in Mermaid notation so they can be rendered in-repo without external tools.
- Whenever a feature is added or removed, a non-functional requirement changes, or a known limitation is identified or resolved, the documentation is updated in the same change.

## Acceptance Criteria

- A user who has never seen the project can follow the README to a working Immich install without referring to any other resource.
- The architecture document contains a Mermaid system diagram and at least two sequence diagrams.
- Every script and its purpose is described somewhere in the documentation.
- After any feature change, the README and architecture document accurately reflect the current system (no documented features that no longer exist, no implemented features absent from the docs).

## Constraints

- Diagrams must use Mermaid notation (rendered natively by GitHub and most documentation platforms).
- The Getting Started section must describe a single-command path to a running system.

## Related Requirements

- All FR entries — every functional capability must be documented.
- NFR-006 — The test suite and how to run it must be documented.
