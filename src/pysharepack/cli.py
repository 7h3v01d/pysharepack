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
from typing import Any, Iterable, Literal

from pysharepack import __version__


Action = Literal["include", "exclude"]
ItemType = Literal["file", "dir"]


DEFAULT_EXCLUDE_PATTERNS = [
    ".git/",
    ".vscode/",
    ".idea/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".venv/",
    "venv/",
    "env/",
    "build/",
    "dist/",
    "htmlcov/",
    "node_modules/",
    "__MACOSX/",
    ".tox/",
    ".nox/",
    ".hypothesis/",
    "*.egg-info/",
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
]

STRICT_EXCLUDE_PATTERNS = [
    ".env",
    ".env.*",
    "secrets/",
    "secret/",
    "private/",
    "keys/",
    "*.key",
    "*.pem",
    "*.crt",
    "*.token",
    "*.secret",
    "config.local.*",
    "secrets.json",
    "secret.json",
]

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

PROTECTED_EXCLUDE_REASONS = {
    "output directory excluded to avoid self-packaging",
    "output ZIP excluded to avoid self-packaging",
}


@dataclass(slots=True)
class Rule:
    """A packaging rule."""

    pattern: str
    action: Action
    source: str
    order: int

    @property
    def normalized(self) -> str:
        return self.pattern.replace("\\", "/")

    @property
    def dir_only(self) -> bool:
        return self.normalized.endswith("/")

    @property
    def is_subtree(self) -> bool:
        p = self.normalized.rstrip("/")
        return self.dir_only or p.endswith("/**")


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
    rules: list[Rule] = field(default_factory=list)


@dataclass(slots=True)
class Config:
    """Optional project configuration."""

    path: Path | None = None
    exclude: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    strict: bool | None = None
    respect_gitignore: bool | None = None
    output: str | None = None
    name: str | None = None


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


def split_parts(rel_posix: str) -> list[str]:
    return [p for p in rel_posix.split("/") if p]


def normalize_pattern(pattern: str) -> str:
    """Normalize a user/config rule pattern."""
    return pattern.strip().replace("\\", "/")


def strip_gitignore_escape(line: str) -> str:
    if line.startswith(r"\#") or line.startswith(r"\!"):
        return line[1:]
    return line


def path_matches_pattern(pattern: str, rel_posix: str, item_type: ItemType) -> bool:
    """
    Match a pysharepack/gitignore-ish pattern against a relative POSIX path.

    Supported behavior:
    - trailing slash means directory/subtree pattern
    - leading slash anchors to project root
    - patterns with slashes match relative paths
    - patterns without slashes match basenames and path components
    - /** suffix matches an entire subtree
    """
    raw = normalize_pattern(pattern)
    if not raw:
        return False

    anchored = raw.startswith("/")
    p = raw[1:] if anchored else raw
    dir_only = p.endswith("/")
    p_no_slash = p.rstrip("/")

    if p_no_slash.endswith("/**"):
        prefix = p_no_slash[:-3].rstrip("/")
        if anchored:
            return rel_posix == prefix or rel_posix.startswith(prefix + "/")
        return any(
            rel_posix == candidate or rel_posix.startswith(candidate + "/")
            for candidate in subtree_candidates(prefix, rel_posix)
        )

    parts = split_parts(rel_posix)
    name = parts[-1] if parts else rel_posix

    if dir_only:
        if item_type == "dir" and (fnmatch.fnmatch(name, p_no_slash) or fnmatch.fnmatch(rel_posix, p_no_slash)):
            return True
        if anchored:
            return rel_posix == p_no_slash or rel_posix.startswith(p_no_slash + "/")
        if "/" in p_no_slash:
            return rel_posix == p_no_slash or rel_posix.startswith(p_no_slash + "/")
        return any(fnmatch.fnmatch(part, p_no_slash) for part in parts)

    if anchored:
        return fnmatch.fnmatch(rel_posix, p)

    if "/" in p:
        return fnmatch.fnmatch(rel_posix, p) or fnmatch.fnmatch("/" + rel_posix, p)

    return fnmatch.fnmatch(name, p) or any(fnmatch.fnmatch(part, p) for part in parts)


def subtree_candidates(prefix: str, rel_posix: str) -> list[str]:
    """Return possible relative subtree prefixes for an unanchored pattern."""
    parts = split_parts(rel_posix)
    prefix_parts = split_parts(prefix)
    if not parts or not prefix_parts:
        return [prefix]
    candidates: list[str] = []
    for i in range(0, len(parts) - len(prefix_parts) + 1):
        candidate = "/".join(parts[i : i + len(prefix_parts)])
        if fnmatch.fnmatch(candidate, prefix):
            candidates.append("/".join(parts[: i + len(prefix_parts)]))
    candidates.append(prefix)
    return candidates


def matching_decision(rel_posix: str, item_type: ItemType, rules: list[Rule]) -> tuple[Action | None, Rule | None]:
    """Return the final matching action and rule. Later rules override earlier rules."""
    final_action: Action | None = None
    final_rule: Rule | None = None
    for rule in rules:
        if path_matches_pattern(rule.pattern, rel_posix, item_type):
            final_action = rule.action
            final_rule = rule
    return final_action, final_rule


def include_may_reopen_dir(rel_posix: str, include_rules: list[Rule]) -> bool:
    """Return True if an include rule appears to target a pruned directory or its subtree."""
    if not rel_posix:
        return True
    dir_name = rel_posix.split("/")[-1]
    for rule in include_rules:
        p = normalize_pattern(rule.pattern).lstrip("/").rstrip("/")
        p = p[:-3].rstrip("/") if p.endswith("/**") else p
        if not p:
            continue
        if "/" not in p and fnmatch.fnmatch(dir_name, p):
            return True
        if p == rel_posix or p.startswith(rel_posix + "/"):
            return True
        if fnmatch.fnmatch(rel_posix, p):
            return True
    return False


def parse_gitignore(project_dir: Path) -> list[Rule]:
    """Parse the project-root .gitignore into best-effort include/exclude rules."""
    gitignore = project_dir / ".gitignore"
    if not gitignore.exists():
        return []

    rules: list[Rule] = []
    order = 0
    for raw_line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        line = strip_gitignore_escape(line.strip())
        if not line or line.startswith("#"):
            continue
        action: Action = "exclude"
        if line.startswith("!"):
            action = "include"
            line = line[1:]
        if not line:
            continue
        rules.append(Rule(line, action, ".gitignore", order))
        order += 1
    return rules


def make_rules(
    *,
    strict: bool,
    respect_gitignore: bool,
    project_dir: Path,
    config_exclude: list[str],
    config_include: list[str],
    cli_exclude: list[str],
    cli_include: list[str],
) -> list[Rule]:
    """Build ordered packaging rules. Later rules win."""
    rules: list[Rule] = []
    order = 0

    def add_many(patterns: Iterable[str], action: Action, source: str) -> None:
        nonlocal order
        for pattern in patterns:
            normalized = normalize_pattern(pattern)
            if not normalized:
                continue
            rules.append(Rule(normalized, action, source, order))
            order += 1

    add_many(DEFAULT_EXCLUDE_PATTERNS, "exclude", "default")
    if strict:
        add_many(STRICT_EXCLUDE_PATTERNS, "exclude", "strict")
    if respect_gitignore:
        for rule in parse_gitignore(project_dir):
            rules.append(Rule(rule.pattern, rule.action, rule.source, order))
            order += 1
    add_many(config_exclude, "exclude", "config exclude")
    add_many(config_include, "include", "config include")
    add_many(cli_exclude, "exclude", "cli exclude")
    add_many(cli_include, "include", "cli include")
    return rules


def should_exclude_output_dir(root_path: Path, project_dir: Path, output_dir: Path | None) -> bool:
    """Return True if root_path is the output directory or inside it."""
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
    respect_gitignore: bool = False,
    output_dir: Path | None = None,
    output_zip: Path | None = None,
    config_exclude: list[str] | None = None,
    config_include: list[str] | None = None,
    cli_exclude: list[str] | None = None,
    cli_include: list[str] | None = None,
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
    config_exclude = config_exclude or []
    config_include = config_include or []
    cli_exclude = cli_exclude or []
    cli_include = cli_include or []

    rules = make_rules(
        strict=strict,
        respect_gitignore=respect_gitignore,
        project_dir=project_dir,
        config_exclude=config_exclude,
        config_include=config_include,
        cli_exclude=cli_exclude,
        cli_include=cli_include,
    )
    result.rules = rules
    include_rules = [rule for rule in rules if rule.action == "include"]

    if resolved_output_dir and is_relative_to(resolved_output_dir, project_dir):
        if same_path(resolved_output_dir, project_dir):
            result.notes.append("Output folder is the project root; the output ZIP path itself will be excluded.")
        else:
            try:
                rel = resolved_output_dir.relative_to(project_dir)
            except ValueError:
                rel = resolved_output_dir
            result.notes.append(f"Output folder is inside the project and will be excluded: {normalise_rel(rel)}")

    if respect_gitignore:
        result.notes.append("Respecting project-root .gitignore patterns where supported.")

    if config_exclude or config_include or cli_exclude or cli_include:
        result.notes.append("Custom include/exclude rules are active; later rules override earlier rules.")

    for root, dirs, files in os.walk(project_dir, followlinks=False):
        root_path = Path(root)

        if should_exclude_output_dir(root_path, project_dir, resolved_output_dir):
            try:
                rel = root_path.relative_to(project_dir)
            except ValueError:
                rel = root_path
            result.excluded.append(Decision(root_path, rel, "output directory excluded to avoid self-packaging"))
            dirs[:] = []
            continue

        kept_dirs: list[str] = []
        for dir_name in dirs:
            dir_path = root_path / dir_name
            rel_path = dir_path.relative_to(project_dir)
            rel_posix = normalise_rel(rel_path)

            if dir_path.is_symlink():
                result.skipped_symlinks.append(Decision(dir_path, rel_path, "symlink directory skipped"))
                continue

            if dir_name in CLEAN_DIR_NAMES:
                result.clean_dirs.append(dir_path)

            action, rule = matching_decision(rel_posix, "dir", rules)
            if action == "exclude" and rule:
                if include_may_reopen_dir(rel_posix, include_rules):
                    kept_dirs.append(dir_name)
                else:
                    result.excluded.append(Decision(dir_path, rel_path, f"{rule.source}: {rule.pattern}"))
                continue

            kept_dirs.append(dir_name)

        dirs[:] = kept_dirs

        for file_name in files:
            file_path = root_path / file_name
            rel_path = file_path.relative_to(project_dir)
            rel_posix = normalise_rel(rel_path)

            if resolved_output_zip and same_path(file_path, resolved_output_zip):
                result.excluded.append(Decision(file_path, rel_path, "output ZIP excluded to avoid self-packaging"))
                continue

            if file_path.is_symlink():
                result.skipped_symlinks.append(Decision(file_path, rel_path, "symlink file skipped"))
                continue

            if matches_any_pattern(file_name, CLEAN_FILE_PATTERNS):
                result.clean_files.append(file_path)

            action, rule = matching_decision(rel_posix, "file", rules)
            if action == "exclude" and rule:
                result.excluded.append(Decision(file_path, rel_path, f"{rule.source}: {rule.pattern}"))
            else:
                result.included_files.append(file_path)

    return result


def simulate_cleaned_scan(scan: ScanResult) -> ScanResult:
    """Return a copy of scan with clean targets removed from package reporting."""
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
        rules=scan.rules,
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


def parse_simple_toml(text: str) -> dict[str, Any]:
    """Very small fallback parser for simple [tool.pysharepack] config files."""
    result: dict[str, Any] = {}
    active = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            active = line.strip("[]") in {"tool.pysharepack", "pysharepack"}
            continue
        if not active or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        value = value.split(" #", 1)[0].strip()
        if value.lower() in {"true", "false"}:
            result[key] = value.lower() == "true"
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                result[key] = []
            else:
                items = []
                for piece in inner.split(","):
                    piece = piece.strip().strip('"').strip("'")
                    if piece:
                        items.append(piece)
                result[key] = items
        else:
            result[key] = value.strip('"').strip("'")
    return {"tool": {"pysharepack": result}}


def read_toml(path: Path) -> dict[str, Any]:
    """Read TOML using tomllib where available, with a tiny fallback."""
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        import tomllib  # Python 3.11+

        return tomllib.loads(text)
    except ModuleNotFoundError:
        return parse_simple_toml(text)


def as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def find_config(project_dir: Path, explicit_config: str | None, no_config: bool) -> Config:
    """Load optional .pysharepack.toml or [tool.pysharepack] config."""
    if no_config:
        return Config()

    candidates: list[Path] = []
    if explicit_config:
        candidates.append(Path(explicit_config).expanduser())
    else:
        candidates.append(project_dir / ".pysharepack.toml")
        candidates.append(project_dir / "pyproject.toml")

    for candidate in candidates:
        if not candidate.exists():
            continue
        data = read_toml(candidate)
        if candidate.name == ".pysharepack.toml":
            section = data.get("tool", {}).get("pysharepack", data.get("pysharepack", data))
        else:
            section = data.get("tool", {}).get("pysharepack")
        if not isinstance(section, dict):
            continue
        return Config(
            path=candidate,
            exclude=as_str_list(section.get("exclude")),
            include=as_str_list(section.get("include")),
            strict=section.get("strict") if isinstance(section.get("strict"), bool) else None,
            respect_gitignore=section.get("respect_gitignore") if isinstance(section.get("respect_gitignore"), bool) else None,
            output=str(section.get("output")) if section.get("output") is not None else None,
            name=str(section.get("name")) if section.get("name") is not None else None,
        )

    if explicit_config:
        print(f"WARNING: config file not found or invalid: {explicit_config}", file=sys.stderr)
    return Config()


def print_summary(
    *,
    project_dir: Path,
    output_zip: Path | None,
    scan: ScanResult,
    strict: bool,
    respect_gitignore: bool,
    dry_run: bool,
    clean: bool,
    config: Config,
    cli_exclude: list[str],
    cli_include: list[str],
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
    print(f"Gitignore:     {'on' if respect_gitignore else 'off'}")
    print(f"Clean mode:    {'on' if clean else 'off'}")
    if config.path:
        print(f"Config:        {config.path}")
    if output_zip:
        print(f"Output ZIP:    {output_zip}")

    if scan.notes:
        print()
        print("Notes:")
        for note in scan.notes:
            print(f"  - {note}")

    custom_count = len(config.exclude) + len(config.include) + len(cli_exclude) + len(cli_include)
    if custom_count:
        print()
        print("Custom rules:")
        print(f"  Config exclude: {len(config.exclude)}")
        print(f"  Config include: {len(config.include)}")
        print(f"  CLI exclude:    {len(cli_exclude)}")
        print(f"  CLI include:    {len(cli_include)}")

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


def print_rules(rules: list[Rule]) -> None:
    """Print the active ordered rule set."""
    print()
    print("Active rules, in priority order; later rules override earlier rules:")
    for rule in rules:
        print(f"  {rule.order:03d} {rule.action.upper():7s} {rule.pattern!r}  ({rule.source})")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="packproject",
        description="Create a clean ZIP of a Python project for sharing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("project", nargs="?", default=".", help="Project directory to package.")
    parser.add_argument("--output", "-o", default=None, help="Output folder for the ZIP.")
    parser.add_argument("--name", "-n", default=None, help="Custom base name for the ZIP. Timestamp is still appended.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be included/excluded without creating a ZIP.")
    parser.add_argument("--clean", action="store_true", help="Delete only safe cache junk before packaging.")
    parser.add_argument("--strict", action=argparse.BooleanOptionalAction, default=None, help="Also exclude private/security-sensitive files like .env and keys.")
    parser.add_argument("--respect-gitignore", action=argparse.BooleanOptionalAction, default=None, help="Apply project-root .gitignore patterns where supported.")
    parser.add_argument("--exclude", action="append", default=[], help="Add an extra exclusion pattern. Can be used multiple times.")
    parser.add_argument("--include", action="append", default=[], help="Add an include override pattern. Later include rules can override exclusions.")
    parser.add_argument("--config", default=None, help="Path to a .pysharepack.toml-style config file.")
    parser.add_argument("--no-config", action="store_true", help="Ignore .pysharepack.toml and pyproject.toml configuration.")
    parser.add_argument("--overwrite", action="store_true", help="Allow overwriting an existing ZIP with the same name.")
    parser.add_argument("--list-included", action="store_true", help="Print every included file.")
    parser.add_argument("--list-excluded", action="store_true", help="Print every excluded item.")
    parser.add_argument("--list-skipped", action="store_true", help="Print every skipped symlink.")
    parser.add_argument("--list-rules", action="store_true", help="Print the active rule set.")
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

    config = find_config(project_dir, args.config, args.no_config)

    strict = args.strict if args.strict is not None else bool(config.strict)
    respect_gitignore = args.respect_gitignore if args.respect_gitignore is not None else bool(config.respect_gitignore)

    output_value = args.output or config.output
    if output_value:
        output_dir = Path(output_value).expanduser()
        if not output_dir.is_absolute():
            output_dir = (project_dir / output_dir).resolve()
        else:
            output_dir = output_dir.resolve()
    else:
        output_dir = project_dir.parent / "packaged"

    name_value = args.name or config.name
    output_zip = output_dir / build_zip_name(project_dir, name_value)

    scan = scan_project(
        project_dir,
        strict=strict,
        respect_gitignore=respect_gitignore,
        output_dir=output_dir,
        output_zip=output_zip,
        config_exclude=config.exclude,
        config_include=config.include,
        cli_exclude=args.exclude,
        cli_include=args.include,
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
                strict=strict,
                respect_gitignore=respect_gitignore,
                output_dir=output_dir,
                output_zip=output_zip,
                config_exclude=config.exclude,
                config_include=config.include,
                cli_exclude=args.exclude,
                cli_include=args.include,
            )

    if args.list_rules:
        print_rules(scan.rules)

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
            zip_uncompressed_bytes = create_zip(project_dir, scan.included_files, output_zip, overwrite=args.overwrite)
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
        strict=strict,
        respect_gitignore=respect_gitignore,
        dry_run=args.dry_run,
        clean=args.clean,
        config=config,
        cli_exclude=args.exclude,
        cli_include=args.include,
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
