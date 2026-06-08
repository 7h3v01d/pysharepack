"""
pysharepack.cli

A small, safe Python project packaging CLI.

Purpose:
    Create a clean ZIP of a Python project for sharing/uploading.

Default behaviour:
    - Does NOT delete or modify your project.
    - Excludes common Python/build/editor/cache folders from the ZIP.
    - Keeps tests, docs, README, LICENSE, requirements, logs, media, and existing ZIP files.

Optional:
    --clean       Deletes only disposable cache junk before packaging.
    --dry-run     Shows what would happen without creating a ZIP or deleting anything.
    --strict      Adds extra privacy/security exclusions such as .env and key files.

Standard library only.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from pysharepack import __version__


# Directories excluded from ZIP by default.
DEFAULT_EXCLUDE_DIR_NAMES = {
    ".git",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    "htmlcov",
}

# Directory name patterns excluded from ZIP by default.
DEFAULT_EXCLUDE_DIR_PATTERNS = {
    "*.egg-info",
}

# File names/patterns excluded from ZIP by default.
DEFAULT_EXCLUDE_FILE_PATTERNS = {
    "*.pyc",
    "*.pyo",
    ".coverage",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    ".DS_Store",
    "Thumbs.db",
}

# Extra privacy/security exclusions only when --strict is used.
STRICT_EXCLUDE_DIR_NAMES = {
    "secrets",
    "secret",
    "private",
    "keys",
}

STRICT_EXCLUDE_FILE_PATTERNS = {
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    "*.crt",
    "*.token",
    "*.secret",
    "config.local.*",
    "secrets.json",
    "secret.json",
}

# Things --clean is allowed to delete.
# Deliberately conservative: no venv, no build/dist, no logs, no DBs, no ZIPs.
CLEAN_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

CLEAN_FILE_PATTERNS = {
    "*.pyc",
    "*.pyo",
}


@dataclass
class Decision:
    path: Path
    rel_path: Path
    reason: str


@dataclass
class ScanResult:
    included_files: list[Path] = field(default_factory=list)
    excluded: list[Decision] = field(default_factory=list)
    clean_dirs: list[Path] = field(default_factory=list)
    clean_files: list[Path] = field(default_factory=list)


def normalise_rel(path: Path) -> str:
    """Return a stable POSIX-style relative path for ZIP entries and output."""
    return path.as_posix()


def matches_any_pattern(name: str, patterns: Iterable[str]) -> str | None:
    """Return the first matching pattern, or None."""
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return pattern
    return None


def is_inside(path: Path, possible_parent: Path) -> bool:
    """Return True if path is inside possible_parent."""
    try:
        path.resolve().relative_to(possible_parent.resolve())
        return True
    except ValueError:
        return False


def should_exclude_dir(
    dir_name: str,
    *,
    strict: bool,
) -> str | None:
    """Return exclusion reason for a directory name, or None."""
    if dir_name in DEFAULT_EXCLUDE_DIR_NAMES:
        return f"default directory exclusion: {dir_name}"

    matched = matches_any_pattern(dir_name, DEFAULT_EXCLUDE_DIR_PATTERNS)
    if matched:
        return f"default directory pattern: {matched}"

    if strict and dir_name in STRICT_EXCLUDE_DIR_NAMES:
        return f"strict directory exclusion: {dir_name}"

    return None


def should_exclude_file(
    file_name: str,
    *,
    strict: bool,
) -> str | None:
    """Return exclusion reason for a file name, or None."""
    matched = matches_any_pattern(file_name, DEFAULT_EXCLUDE_FILE_PATTERNS)
    if matched:
        return f"default file pattern: {matched}"

    if strict:
        matched = matches_any_pattern(file_name, STRICT_EXCLUDE_FILE_PATTERNS)
        if matched:
            return f"strict file pattern: {matched}"

    return None


def scan_project(
    project_dir: Path,
    *,
    strict: bool,
    output_dir: Path | None = None,
) -> ScanResult:
    """
    Scan the project and decide what gets included/excluded.

    output_dir is excluded if it sits inside the project, so the package output
    folder does not get accidentally included.
    """
    result = ScanResult()
    project_dir = project_dir.resolve()
    resolved_output_dir = output_dir.resolve() if output_dir else None

    for root, dirs, files in os.walk(project_dir):
        root_path = Path(root)

        # If output dir is inside the project, avoid including it.
        if resolved_output_dir and is_inside(root_path, resolved_output_dir):
            try:
                rel = root_path.relative_to(project_dir)
            except ValueError:
                rel = root_path
            result.excluded.append(
                Decision(root_path, rel, "output directory excluded to avoid self-packaging")
            )
            dirs[:] = []
            continue

        # Mutate dirs in-place so os.walk does not descend into excluded folders.
        kept_dirs: list[str] = []
        for dir_name in dirs:
            dir_path = root_path / dir_name
            rel_path = dir_path.relative_to(project_dir)

            if dir_name in CLEAN_DIR_NAMES:
                result.clean_dirs.append(dir_path)

            reason = should_exclude_dir(dir_name, strict=strict)
            if reason:
                result.excluded.append(Decision(dir_path, rel_path, reason))
            else:
                kept_dirs.append(dir_name)

        dirs[:] = kept_dirs

        for file_name in files:
            file_path = root_path / file_name
            rel_path = file_path.relative_to(project_dir)

            if matches_any_pattern(file_name, CLEAN_FILE_PATTERNS):
                result.clean_files.append(file_path)

            reason = should_exclude_file(file_name, strict=strict)
            if reason:
                result.excluded.append(Decision(file_path, rel_path, reason))
            else:
                result.included_files.append(file_path)

    return result


def remove_clean_targets(scan: ScanResult, *, dry_run: bool) -> tuple[int, int]:
    """Delete cache junk collected during scan. Returns (dirs_removed, files_removed)."""
    dirs_removed = 0
    files_removed = 0

    # Delete files first, then dirs.
    for file_path in scan.clean_files:
        if not file_path.exists():
            continue
        if not dry_run:
            try:
                file_path.unlink()
            except OSError as exc:
                print(f"WARNING: could not delete file {file_path}: {exc}", file=sys.stderr)
                continue
        files_removed += 1

    # Sort deepest first for predictable cleanup.
    for dir_path in sorted(scan.clean_dirs, key=lambda p: len(p.parts), reverse=True):
        if not dir_path.exists():
            continue
        if not dry_run:
            try:
                shutil.rmtree(dir_path)
            except OSError as exc:
                print(f"WARNING: could not delete directory {dir_path}: {exc}", file=sys.stderr)
                continue
        dirs_removed += 1

    return dirs_removed, files_removed


def build_zip_name(project_dir: Path, custom_name: str | None) -> str:
    """Build a timestamped ZIP filename."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    base = custom_name.strip() if custom_name else project_dir.name
    base = base[:-4] if base.lower().endswith(".zip") else base
    safe_base = "".join(c if c.isalnum() or c in "._-" else "_" for c in base).strip("._")
    if not safe_base:
        safe_base = "project"
    return f"{safe_base}_{timestamp}.zip"


def create_zip(
    project_dir: Path,
    included_files: list[Path],
    output_zip: Path,
    *,
    overwrite: bool,
) -> int:
    """Create the ZIP. Returns total uncompressed bytes written."""
    if output_zip.exists() and not overwrite:
        raise FileExistsError(
            f"Output already exists: {output_zip}\n"
            "Use --overwrite or choose a different --name/--output."
        )

    output_zip.parent.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(included_files):
            rel_path = file_path.relative_to(project_dir)
            arcname = normalise_rel(rel_path)
            zf.write(file_path, arcname)
            try:
                total_bytes += file_path.stat().st_size
            except OSError:
                pass

    return total_bytes


def format_bytes(num: int) -> str:
    """Human-readable byte formatting."""
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{num} B"


def print_summary(
    *,
    project_dir: Path,
    output_zip: Path | None,
    scan: ScanResult,
    strict: bool,
    dry_run: bool,
    clean: bool,
    cleaned_dirs: int = 0,
    cleaned_files: int = 0,
    zip_uncompressed_bytes: int = 0,
) -> None:
    """Print a concise packaging report."""
    print()
    print("=" * 72)
    print("pysharepack summary")
    print("=" * 72)
    print(f"Project:       {project_dir}")
    print(f"Mode:          {'DRY RUN' if dry_run else 'WRITE'}")
    print(f"Strict mode:   {'on' if strict else 'off'}")
    print(f"Clean mode:    {'on' if clean else 'off'}")
    if output_zip:
        print(f"Output ZIP:    {output_zip}")

    print()
    print(f"Included files:          {len(scan.included_files)}")
    print(f"Excluded items:          {len(scan.excluded)}")
    print(f"Cleanable cache dirs:    {len(scan.clean_dirs)}")
    print(f"Cleanable cache files:   {len(scan.clean_files)}")

    if clean:
        action = "Would remove" if dry_run else "Removed"
        print(f"{action} cache dirs:      {cleaned_dirs}")
        print(f"{action} cache files:     {cleaned_files}")

    if output_zip and output_zip.exists() and not dry_run:
        try:
            print(f"ZIP file size:           {format_bytes(output_zip.stat().st_size)}")
        except OSError:
            pass
        print(f"Uncompressed included:   {format_bytes(zip_uncompressed_bytes)}")

    if scan.excluded:
        print()
        print("Excluded preview:")
        for item in scan.excluded[:30]:
            print(f"  - {normalise_rel(item.rel_path)}  ({item.reason})")
        if len(scan.excluded) > 30:
            print(f"  ... plus {len(scan.excluded) - 30} more excluded item(s)")

    if dry_run:
        print()
        print("Dry run only: no ZIP was created and no files were deleted.")

    print("=" * 72)
    print()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a clean ZIP of a Python project for sharing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="Project directory to package.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output folder for the ZIP. Defaults to ./packaged beside the project.",
    )
    parser.add_argument(
        "--name",
        "-n",
        default=None,
        help="Custom base name for the ZIP. Timestamp is still appended.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be included/excluded without creating a ZIP.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete only safe cache junk before packaging.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also exclude private/security-sensitive files like .env and keys.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting an existing ZIP with the same name.",
    )
    parser.add_argument(
        "--list-included",
        action="store_true",
        help="Print every included file.",
    )
    parser.add_argument(
        "--list-excluded",
        action="store_true",
        help="Print every excluded item.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"pysharepack {__version__}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    project_dir = Path(args.project).expanduser().resolve()
    if not project_dir.exists():
        print(f"ERROR: project path does not exist: {project_dir}", file=sys.stderr)
        return 2
    if not project_dir.is_dir():
        print(f"ERROR: project path is not a directory: {project_dir}", file=sys.stderr)
        return 2

    if args.output:
        output_dir = Path(args.output).expanduser().resolve()
    else:
        output_dir = project_dir.parent / "packaged"

    output_zip = output_dir / build_zip_name(project_dir, args.name)

    scan = scan_project(project_dir, strict=args.strict, output_dir=output_dir)

    if args.list_included:
        print()
        print("Included files:")
        for file_path in sorted(scan.included_files):
            print(f"  + {normalise_rel(file_path.relative_to(project_dir))}")

    if args.list_excluded:
        print()
        print("Excluded items:")
        for item in scan.excluded:
            print(f"  - {normalise_rel(item.rel_path)}  ({item.reason})")

    cleaned_dirs = 0
    cleaned_files = 0
    if args.clean:
        cleaned_dirs, cleaned_files = remove_clean_targets(scan, dry_run=args.dry_run)

        # If actual cleaning happened, rescan so deleted junk no longer appears.
        if not args.dry_run:
            scan = scan_project(project_dir, strict=args.strict, output_dir=output_dir)

    zip_uncompressed_bytes = 0
    if not args.dry_run:
        try:
            zip_uncompressed_bytes = create_zip(
                project_dir,
                scan.included_files,
                output_zip,
                overwrite=args.overwrite,
            )
        except FileExistsError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 3
        except OSError as exc:
            print(f"ERROR: could not create ZIP: {exc}", file=sys.stderr)
            return 4

    print_summary(
        project_dir=project_dir,
        output_zip=output_zip,
        scan=scan,
        strict=args.strict,
        dry_run=args.dry_run,
        clean=args.clean,
        cleaned_dirs=cleaned_dirs,
        cleaned_files=cleaned_files,
        zip_uncompressed_bytes=zip_uncompressed_bytes,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
