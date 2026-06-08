"""
pysharepack CLI.

A safe, dependency-free Python project ZIP packager.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import sys
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

from pysharepack import __version__


DEFAULT_EXCLUDE_DIR_NAMES = {
    ".git",
    ".vscode",
    ".idea",
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
    "node_modules",
    "__MACOSX",
    ".tox",
    ".nox",
    ".hypothesis",
}

DEFAULT_EXCLUDE_DIR_PATTERNS = {
    "*.egg-info",
}

DEFAULT_EXCLUDE_FILE_PATTERNS = {
    "*.pyc",
    "*.pyo",
    ".coverage",
    ".coverage.*",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "*.tmp",
    "*.temp",
    ".DS_Store",
    "Thumbs.db",
}

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


@dataclass(slots=True)
class Decision:
    """A path exclusion or skip decision."""

    path: Path
    rel_path: Path
    reason: str


@dataclass(slots=True)
class ScanResult:
    """Scan results for packaging and optional cleanup."""

    included_files: list[Path] = field(default_factory=list)
    excluded: list[Decision] = field(default_factory=list)
    skipped_symlinks: list[Decision] = field(default_factory=list)
    clean_dirs: list[Path] = field(default_factory=list)
    clean_files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def normalise_rel(path: Path) -> str:
    """Return a stable POSIX-style relative path for ZIP entries and output."""
    return path.as_posix()


def matches_any_pattern(name: str, patterns: Iterable[str]) -> str | None:
    """Return the first matching fnmatch pattern, or None."""
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return pattern
    return None


def is_relative_to(path: Path, possible_parent: Path) -> bool:
    """Backport-friendly Path.is_relative_to helper."""
    try:
        path.resolve().relative_to(possible_parent.resolve())
        return True
    except ValueError:
        return False


def same_path(left: Path, right: Path) -> bool:
    """Return True when two paths resolve to the same filesystem location."""
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.absolute() == right.absolute()


def should_exclude_dir(dir_name: str, *, strict: bool) -> str | None:
    """Return the exclusion reason for a directory name, or None."""
    if dir_name in DEFAULT_EXCLUDE_DIR_NAMES:
        return f"default directory exclusion: {dir_name}"

    matched = matches_any_pattern(dir_name, DEFAULT_EXCLUDE_DIR_PATTERNS)
    if matched:
        return f"default directory pattern: {matched}"

    if strict and dir_name in STRICT_EXCLUDE_DIR_NAMES:
        return f"strict directory exclusion: {dir_name}"

    return None


def should_exclude_file(file_name: str, *, strict: bool) -> str | None:
    """Return the exclusion reason for a file name, or None."""
    matched = matches_any_pattern(file_name, DEFAULT_EXCLUDE_FILE_PATTERNS)
    if matched:
        return f"default file pattern: {matched}"

    if strict:
        matched = matches_any_pattern(file_name, STRICT_EXCLUDE_FILE_PATTERNS)
        if matched:
            return f"strict file pattern: {matched}"

    return None


def should_exclude_output_dir(root_path: Path, project_dir: Path, output_dir: Path | None) -> bool:
    """
    Return True if root_path is the output directory or inside it.

    The project root itself is not excluded when --output points at the project root.
    In that case only the output ZIP path is excluded explicitly.
    """
    if output_dir is None:
        return False

    resolved_project = project_dir.resolve()
    resolved_output = output_dir.resolve()

    if same_path(resolved_output, resolved_project):
        return False

    return is_relative_to(resolved_output, resolved_project) and is_relative_to(root_path, resolved_output)


def scan_project(
    project_dir: Path,
    *,
    strict: bool,
    output_dir: Path | None = None,
    output_zip: Path | None = None,
) -> ScanResult:
    """
    Scan the project and decide what gets included/excluded.

    If output_dir is inside project_dir, it is excluded so the package output folder
    does not accidentally package itself. Symlinks are skipped and reported.
    """
    result = ScanResult()
    project_dir = project_dir.resolve()
    resolved_output_dir = output_dir.resolve() if output_dir else None
    resolved_output_zip = output_zip.resolve() if output_zip else None

    if resolved_output_dir and is_relative_to(resolved_output_dir, project_dir):
        if same_path(resolved_output_dir, project_dir):
            result.notes.append("Output folder is the project root; the output ZIP path itself will be excluded.")
        else:
            try:
                rel = resolved_output_dir.relative_to(project_dir)
            except ValueError:
                rel = resolved_output_dir
            result.notes.append(f"Output folder is inside the project and will be excluded: {normalise_rel(rel)}")

    for root, dirs, files in os.walk(project_dir, followlinks=False):
        root_path = Path(root)

        if should_exclude_output_dir(root_path, project_dir, resolved_output_dir):
            try:
                rel = root_path.relative_to(project_dir)
            except ValueError:
                rel = root_path
            result.excluded.append(
                Decision(root_path, rel, "output directory excluded to avoid self-packaging")
            )
            dirs[:] = []
            continue

        kept_dirs: list[str] = []
        for dir_name in dirs:
            dir_path = root_path / dir_name
            rel_path = dir_path.relative_to(project_dir)

            if dir_path.is_symlink():
                result.skipped_symlinks.append(
                    Decision(dir_path, rel_path, "symlink directory skipped")
                )
                continue

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

            if resolved_output_zip and same_path(file_path, resolved_output_zip):
                result.excluded.append(
                    Decision(file_path, rel_path, "output ZIP excluded to avoid self-packaging")
                )
                continue

            if file_path.is_symlink():
                result.skipped_symlinks.append(
                    Decision(file_path, rel_path, "symlink file skipped")
                )
                continue

            if matches_any_pattern(file_name, CLEAN_FILE_PATTERNS):
                result.clean_files.append(file_path)

            reason = should_exclude_file(file_name, strict=strict)
            if reason:
                result.excluded.append(Decision(file_path, rel_path, reason))
            else:
                result.included_files.append(file_path)

    return result


def simulate_cleaned_scan(scan: ScanResult) -> ScanResult:
    """
    Return a copy of scan with clean targets removed from package reporting.

    Used for --clean --dry-run so the summary reflects the simulated post-clean state.
    """
    clean_paths = {p.resolve() for p in scan.clean_dirs}
    clean_paths.update(p.resolve() for p in scan.clean_files)

    def is_clean_target_or_inside(path: Path) -> bool:
        resolved = path.resolve()
        return any(resolved == clean_path or is_relative_to(resolved, clean_path) for clean_path in clean_paths)

    return ScanResult(
        included_files=[p for p in scan.included_files if not is_clean_target_or_inside(p)],
        excluded=[d for d in scan.excluded if not is_clean_target_or_inside(d.path)],
        skipped_symlinks=[d for d in scan.skipped_symlinks if not is_clean_target_or_inside(d.path)],
        clean_dirs=[],
        clean_files=[],
        notes=[*scan.notes, "Clean dry-run: summary reflects package state after simulated cleanup."],
    )


def remove_clean_targets(scan: ScanResult, *, dry_run: bool) -> tuple[int, int]:
    """Delete cache junk collected during scan. Returns (dirs_removed, files_removed)."""
    dirs_removed = 0
    files_removed = 0

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


def sanitize_base_name(base: str) -> str:
    """Create a conservative, filesystem-friendly base name."""
    normalized = unicodedata.normalize("NFKD", base)
    safe = re.sub(r"[^\w._-]+", "_", normalized, flags=re.ASCII)
    safe = re.sub(r"_+", "_", safe).strip("._-")
    return safe or "project"


def build_zip_name(project_dir: Path, custom_name: str | None) -> str:
    """Build a timestamped ZIP filename."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    base = custom_name.strip() if custom_name else project_dir.name
    base = base[:-4] if base.lower().endswith(".zip") else base
    safe_base = sanitize_base_name(base)
    return f"{safe_base}_{timestamp}.zip"


def create_zip(project_dir: Path, included_files: list[Path], output_zip: Path, *, overwrite: bool) -> int:
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
            if file_path.is_symlink():
                continue
            rel_path = file_path.relative_to(project_dir)
            arcname = normalise_rel(rel_path)
            zf.write(file_path, arcname)
            try:
                total_bytes += file_path.stat().st_size
            except OSError:
                pass

        zf.comment = f"Created by pysharepack {__version__}".encode("utf-8")

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
    cleanable_dirs_before: int = 0,
    cleanable_files_before: int = 0,
    cleaned_dirs: int = 0,
    cleaned_files: int = 0,
    zip_uncompressed_bytes: int = 0,
) -> None:
    """Print a packaging report."""
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

    if scan.notes:
        print()
        print("Notes:")
        for note in scan.notes:
            print(f"  - {note}")

    print()
    print(f"Included files:          {len(scan.included_files)}")
    print(f"Excluded items:          {len(scan.excluded)}")
    print(f"Skipped symlinks:        {len(scan.skipped_symlinks)}")

    if clean:
        print(f"Cleanable cache dirs:    {cleanable_dirs_before}")
        print(f"Cleanable cache files:   {cleanable_files_before}")
        action = "Would remove" if dry_run else "Removed"
        print(f"{action} cache dirs:      {cleaned_dirs}")
        print(f"{action} cache files:     {cleaned_files}")
    else:
        print(f"Cleanable cache dirs:    {len(scan.clean_dirs)}")
        print(f"Cleanable cache files:   {len(scan.clean_files)}")

    if output_zip and output_zip.exists() and not dry_run:
        try:
            print(f"ZIP file size:           {format_bytes(output_zip.stat().st_size)}")
        except OSError:
            pass
        print(f"Uncompressed included:   {format_bytes(zip_uncompressed_bytes)}")

    if scan.skipped_symlinks:
        print()
        print("Skipped symlink preview:")
        for item in scan.skipped_symlinks[:20]:
            print(f"  ~ {normalise_rel(item.rel_path)}  ({item.reason})")
        if len(scan.skipped_symlinks) > 20:
            print(f"  ... plus {len(scan.skipped_symlinks) - 20} more skipped symlink(s)")

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
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="packproject",
        description="Create a clean ZIP of a Python project for sharing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("project", nargs="?", default=".", help="Project directory to package.")
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output folder for the ZIP. Defaults to a packaged folder beside the project.",
    )
    parser.add_argument(
        "--name",
        "-n",
        default=None,
        help="Custom base name for the ZIP. Timestamp is still appended.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be included/excluded without creating a ZIP.")
    parser.add_argument("--clean", action="store_true", help="Delete only safe cache junk before packaging.")
    parser.add_argument("--strict", action="store_true", help="Also exclude private/security-sensitive files like .env and keys.")
    parser.add_argument("--overwrite", action="store_true", help="Allow overwriting an existing ZIP with the same name.")
    parser.add_argument("--list-included", action="store_true", help="Print every included file.")
    parser.add_argument("--list-excluded", action="store_true", help="Print every excluded item.")
    parser.add_argument("--list-skipped", action="store_true", help="Print every skipped symlink.")
    parser.add_argument("--version", action="version", version=f"pysharepack {__version__}")
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    """Run the CLI and return an exit code."""
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

    scan = scan_project(
        project_dir,
        strict=args.strict,
        output_dir=output_dir,
        output_zip=output_zip,
    )

    cleanable_dirs_before = len(scan.clean_dirs)
    cleanable_files_before = len(scan.clean_files)

    cleaned_dirs = 0
    cleaned_files = 0
    if args.clean:
        cleaned_dirs, cleaned_files = remove_clean_targets(scan, dry_run=args.dry_run)

        if args.dry_run:
            scan = simulate_cleaned_scan(scan)
        else:
            scan = scan_project(
                project_dir,
                strict=args.strict,
                output_dir=output_dir,
                output_zip=output_zip,
            )

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

    if args.list_skipped:
        print()
        print("Skipped symlinks:")
        for item in scan.skipped_symlinks:
            print(f"  ~ {normalise_rel(item.rel_path)}  ({item.reason})")

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
        cleanable_dirs_before=cleanable_dirs_before,
        cleanable_files_before=cleanable_files_before,
        cleaned_dirs=cleaned_dirs,
        cleaned_files=cleaned_files,
        zip_uncompressed_bytes=zip_uncompressed_bytes,
    )

    return 0


def main() -> None:
    """Console-script entry point."""
    raise SystemExit(run())


if __name__ == "__main__":
    main()
