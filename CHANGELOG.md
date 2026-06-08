# Changelog

## 0.2.0

Configurability release.

- Added `--exclude` for custom exclusion patterns.
- Added `--include` for include override patterns.
- Added `.pysharepack.toml` config support.
- Added `[tool.pysharepack]` support in `pyproject.toml`.
- Added `--config` and `--no-config`.
- Added optional `--respect-gitignore` support for project-root `.gitignore` patterns.
- Added `--list-rules` to inspect active rules and rule precedence.
- Refactored exclusions into an ordered rule engine where later rules override earlier rules.
- Preserved 0.1.1 safety behavior: symlinks are skipped, output ZIP safety is protected, and `--clean` remains conservative.

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
