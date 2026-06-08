# Changelog

## 0.1.1

Hardening release.

- Added explicit symlink skipping and reporting.
- Improved `--clean --dry-run` behavior so the summary reflects the simulated post-clean package state.
- Improved output folder handling when the output directory is inside the project.
- Explicitly excludes the output ZIP path when the output folder is the project root.
- Added default exclusions for `.idea/`, `node_modules/`, `__MACOSX/`, `.tox/`, `.nox/`, `.hypothesis/`, `*.tmp`, and `*.temp`.
- Added ZIP comment metadata with the pysharepack version.
- Improved filename sanitization.
- Added tests for strict mode, clean dry-run simulation, output folder edge cases, and symlink skipping.
- Expanded README with strict mode guidance, symlink handling, output behavior, and limitations.

## 0.1.0

Initial alpha release.

- Added dependency-free CLI for safe Python project ZIP packaging.
- Added default exclusions for Git, VS Code, virtual environments, build outputs, caches, bytecode, and local databases.
- Kept tests, docs, logs, media, README/LICENSE/requirements files, and existing archives by default.
- Added optional strict privacy mode.
- Added optional safe cache cleanup mode.
- Added console commands: `packproject` and `pysharepack`.
