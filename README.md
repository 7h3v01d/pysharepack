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
- Optional `--strict` mode for more privacy-sensitive packaging.

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

- Does not currently read `.gitignore`.
- Does not currently support custom `--include` / `--exclude` override patterns.
- Does not currently preserve symlinks.
- Strict mode is not a secret scanner.
- Very large projects may benefit from future progress output and custom rule support.

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

MIT.
