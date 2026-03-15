## Autonomy
1. Do not ask for approval before running commands. Read commands, write commands, and script edits are all fine to execute directly.
2. Only ask for approval before large implementation changes (new scripts, architectural changes, destructive operations like deleting data or resetting state).

## Quality
1. When implementing a requirement or fixing a bug, always implement an automated way of testing it.
2. The install script should have automated tests that ensures correctness

## Documentation
1. Always have a README.md file that contains a Getting Started section. This section will describe how in ONE command, you can run it locally. Other commands are described as well in a concise manner.
2. A mermain diagram is always produced. This will describe the system that is built and it will als contain several sequence diagrams.
3. When adding / removing features or improving non functional requirements or acknowledging limitations, always update the documentation to reflect this. 

## Logging
1. When writting code, always add trace, info, Warn and ERROR logs and pipe them to stdout and to a log file that gets cleared  before every start. the log file should be in a dir called logs
2. always inspect the log file before each run and analyse want when wrong and proactively fix it

