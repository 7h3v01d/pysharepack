# pysharepack

`pysharepack` is a small, safe command-line tool for packaging Python projects into clean ZIP files for sharing, uploading, archiving, or sending to an AI assistant.

It is designed for Python developers who frequently need to share project folders but do not want to include virtual environments, Git internals, editor folders, caches, compiled bytecode, or local databases.

## Design goals

- Safe by default.
- No runtime dependencies.
- Does not modify your project unless you explicitly use `--clean`.
- Keeps tests, docs, logs, media, README files, licenses, requirements files, and existing ZIP archives by default.
- Excludes common Python/build/editor/cache junk.
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
*.egg-info/
*.pyc
*.pyo
.coverage
*.db
*.sqlite
*.sqlite3
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

## Strict mode exclusions

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

It does not delete databases, logs, media, archives, docs, source files, virtual environments, Git folders, or config files.

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
