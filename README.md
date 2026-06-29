# pysharepack

`pysharepack` is a small, safe command-line tool for packaging Python projects into clean ZIP files for sharing, uploading, archiving, or sending to an AI assistant.

It is designed for Python developers who frequently need to share project folders but do not want to include virtual environments, Git internals, editor folders, caches, compiled bytecode, local databases, or massive dependency folders.

## Design goals

- Safe by default.
- No runtime dependencies.
- Does not modify your project unless you explicitly use `--clean`.
- Keeps tests, docs, logs, media, README files, licenses, requirements files, and existing ZIP archives by default.
- Excludes common Python/build/editor/cache junk.
- Skips symlinks by default so archives do not accidentally include linked external content.
- Supports custom include/exclude overrides.
- Supports project configuration via `.pysharepack.toml` or `[tool.pysharepack]` in `pyproject.toml`.
- Supports optional project-root `.gitignore` handling.

## Install locally

From the project root:

```bash
python -m pip install -e .
```

Then run:

```bash
packproject --help
```

or:

```bash
pysharepack --help
```

## Basic usage

Package the current project:

```bash
packproject .
```

Package a specific project:

```bash
packproject G:\Projects\MyProject
```

Preview what would happen without creating a ZIP:

```bash
packproject . --dry-run
```

Show included files:

```bash
packproject . --dry-run --list-included
```

Show excluded items:

```bash
packproject . --dry-run --list-excluded
```

Show active rules:

```bash
packproject . --dry-run --list-rules
```

Create a custom-named ZIP in a chosen output folder:

```bash
packproject . --name my_project_share --output clean_zips
```

Run safe cache cleanup before packaging:

```bash
packproject . --clean
```

Run privacy-sensitive packaging:

```bash
packproject . --strict
```

## Custom exclude and include rules

Add extra exclusions:

```bash
packproject . --exclude "*.log" --exclude "large_data/"
```

Add include overrides:

```bash
packproject . --include "*.db"
```

Include rules are applied after exclusion rules, so they can override exclusions. Symlinks and the output ZIP safety exclusions are still protected.

To re-include a file from a normally excluded directory, target the directory or path explicitly:

```bash
packproject . --include ".vscode/settings.json"
```

## Configuration file

Create `.pysharepack.toml` in your project root:

```toml
[tool.pysharepack]
name = "my_project_share"
output = "packaged"
strict = false
respect_gitignore = true
exclude = ["large_data/", "*.bak"]
include = [".vscode/settings.json"]
```

You can also place the same section in `pyproject.toml`:

```toml
[tool.pysharepack]
exclude = ["scratch/", "*.local"]
include = ["docs/private_example.md"]
```

Ignore project config:

```bash
packproject . --no-config
```

Use a specific config file:

```bash
packproject . --config path/to/custom.toml
```

## Optional `.gitignore` support

Enable project-root `.gitignore` handling:

```bash
packproject . --respect-gitignore
```

Or via config:

```toml
[tool.pysharepack]
respect_gitignore = true
```

This is a best-effort implementation, not a full Git engine. It supports common patterns, comments, negation with `!`, directory rules, root-anchored rules, and simple glob matching.

## Default exclusions

By default, these are not included in the ZIP:

```text
.git/
.vscode/
.idea/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.venv/
venv/
env/
build/
dist/
htmlcov/
node_modules/
__MACOSX/
.tox/
.nox/
.hypothesis/
*.egg-info/
*.pyc
*.pyo
.coverage
.coverage.*
*.db
*.sqlite
*.sqlite3
*.tmp
*.temp
.DS_Store
Thumbs.db
```

## Included by default

The tool intentionally keeps:

```text
tests/
test_*.py
*_test.py
docs/
README*
LICENSE*
requirements*.txt
pyproject.toml
images/
media/
*.log
*.zip
*.7z
*.rar
```

## Strict mode

Use `--strict` when you are packaging a project for a wider audience, sending code outside your machine, uploading to a third-party service, or sharing with someone who should not receive local/private configuration.

`--strict` additionally excludes likely private/security-sensitive files:

```text
.env
.env.*
secrets/
secret/
private/
keys/
*.key
*.pem
*.crt
*.token
*.secret
config.local.*
secrets.json
secret.json
```

Strict mode is pattern-based. It is not a full secret scanner. You should still review the dry-run output for sensitive project-specific files.

## Cleanup mode

`--clean` only removes disposable cache junk from the real project:

```text
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.pyc
*.pyo
```

It does not delete databases, logs, media, archives, docs, source files, virtual environments, Git folders, editor folders, or config files.

When combined with `--dry-run`, cleanup is simulated. The summary shows the package state after simulated cleanup and reports what would be removed.

## Symlink handling

Symlinks are skipped and reported by default.

This is intentional. Following symlinks can accidentally pull in files from outside the project, bloat the archive, or include private content. Symlink preservation/following may be added later as an explicit option.

## Output folder behavior

If the output folder is inside the project, pysharepack excludes that output folder from the ZIP so it does not package its own generated archives.

If the output folder is the project root, pysharepack explicitly excludes the output ZIP path itself.

## Limitations

- `.gitignore` support is best-effort and currently reads only the project-root `.gitignore`.
- It does not currently preserve symlinks.
- Strict mode is not a secret scanner.
- Include rules can reopen an excluded directory only when the include rule explicitly targets that directory/path.
- Very large projects may benefit from future progress output.

## Build for PyPI

Install build tools:

```bash
python -m pip install -U build twine
```

Build the package:

```bash
python -m build
```

Check the generated distribution:

```bash
python -m twine check dist/*
```

Upload to TestPyPI first:

```bash
python -m twine upload --repository testpypi dist/*
```

Then upload to PyPI when ready:

```bash
python -m twine upload dist/*
```

## Important before publishing

The package name `pysharepack` may need to be changed if the name is already taken on PyPI. Edit this field in `pyproject.toml`:

```toml
[project]
name = "pysharepack"
```

The import package can remain `pysharepack`, but the PyPI project name must be globally unique.

## License

Apache 2.0 - Leon Priest
