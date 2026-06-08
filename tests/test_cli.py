from __future__ import annotations

import zipfile
from pathlib import Path

from pysharepack.cli import main, scan_project


def make_demo_project(root: Path) -> Path:
    project = root / "demo_project"
    project.mkdir()

    (project / "README.md").write_text("# Demo\n", encoding="utf-8")
    (project / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (project / "test_main.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    (project / "run.log").write_text("keep logs\n", encoding="utf-8")
    (project / "old.zip").write_bytes(b"existing zip should be included")
    (project / "data.db").write_text("local db should be excluded\n", encoding="utf-8")
    (project / ".env").write_text("strict secret\n", encoding="utf-8")

    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("git config\n", encoding="utf-8")

    (project / ".vscode").mkdir()
    (project / ".vscode" / "settings.json").write_text("{}", encoding="utf-8")

    (project / "__pycache__").mkdir()
    (project / "__pycache__" / "main.cpython-311.pyc").write_bytes(b"cache")

    return project


def test_default_scan_keeps_tests_logs_archives_and_excludes_junk(tmp_path: Path) -> None:
    project = make_demo_project(tmp_path)
    scan = scan_project(project, strict=False, output_dir=tmp_path / "out")

    included = {p.relative_to(project).as_posix() for p in scan.included_files}
    excluded = {d.rel_path.as_posix() for d in scan.excluded}

    assert "README.md" in included
    assert "main.py" in included
    assert "test_main.py" in included
    assert "run.log" in included
    assert "old.zip" in included

    assert "data.db" in excluded
    assert ".git" in excluded
    assert ".vscode" in excluded
    assert "__pycache__" in excluded

    # Strict mode is off, so .env is kept by default.
    assert ".env" in included


def test_strict_scan_excludes_env_file(tmp_path: Path) -> None:
    project = make_demo_project(tmp_path)
    scan = scan_project(project, strict=True, output_dir=tmp_path / "out")

    included = {p.relative_to(project).as_posix() for p in scan.included_files}
    excluded = {d.rel_path.as_posix() for d in scan.excluded}

    assert ".env" not in included
    assert ".env" in excluded


def test_run_creates_expected_zip(tmp_path: Path) -> None:
    project = make_demo_project(tmp_path)
    out = tmp_path / "out"

    exit_code = main([str(project), "--output", str(out), "--name", "demo"])
    assert exit_code == 0

    zip_files = list(out.glob("demo_*.zip"))
    assert len(zip_files) == 1

    with zipfile.ZipFile(zip_files[0]) as zf:
        names = set(zf.namelist())

    assert "README.md" in names
    assert "main.py" in names
    assert "test_main.py" in names
    assert "run.log" in names
    assert "old.zip" in names

    assert "data.db" not in names
    assert ".git/config" not in names
    assert ".vscode/settings.json" not in names
    assert "__pycache__/main.cpython-311.pyc" not in names
