#!/usr/bin/env python3
"""CI integrity guard: keeps tests, CI and the contract locked. Standard library only.

PR mode:   python scripts/ci/integrity.py --base origin/main   (PR title read from env PR_TITLE)
Scan mode: python scripts/ci/integrity.py --scan               (push to main: whole tracked tree)

Rules (see scripts/ci/README.md):
  a. Locked paths change only in their own PR, titled [tests] / [ci] / [contract] / [foundation].
     [foundation] may touch anything (used once for the initial foundation PR).
  b. No client data or secrets: data/, .env, .env.* (except .env.example), *.xlsx, *.xls, *.db, *.sqlite.
  c. No skipped / focused tests (skip, xfail, .only) in tests/ or apps/web/e2e/.
  d. --cov-fail-under in .github/workflows/ci.yml must stay >= 90.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

LOCKED_PREFIXES = ("tests/", "apps/web/e2e/", ".github/", "scripts/ci/", "contract/")
LOCKED_FILES = ("pyproject.toml", "requirements-dev.txt")
LOCKED_TAGS = ("[tests]", "[ci]", "[contract]", "[foundation]")
FOUNDATION_TAG = "[foundation]"
RELEASE_TAG = "[release]"  # dev -> main promotion PR only (see is_release_pr)

TEST_PREFIXES = ("tests/", "apps/web/e2e/")
FORBIDDEN_TEST_PATTERNS = (
    "pytest.mark.skip",
    "pytest.skip(",
    "xfail",
    ".only(",
    "test.skip(",
    "describe.skip",
    "it.skip",
)
FORBIDDEN_SUFFIXES = (".xlsx", ".xls", ".db", ".sqlite", ".sqlite3")

CI_WORKFLOW = ".github/workflows/ci.yml"
MIN_COVERAGE = 90.0
COV_RE = re.compile(r"--cov-fail-under[= ]+([0-9]+(?:\.[0-9]+)?)")

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- helpers
def _norm(path: str) -> str:
    p = path.strip().replace("\\", "/")
    return p[2:] if p.startswith("./") else p


def is_locked(path: str) -> bool:
    p = _norm(path)
    return p in LOCKED_FILES or p.startswith(LOCKED_PREFIXES)


def is_test_file(path: str) -> bool:
    return _norm(path).startswith(TEST_PREFIXES)


def is_forbidden_data(path: str) -> bool:
    p = _norm(path)
    name = p.rsplit("/", 1)[-1]
    if p.startswith("data/"):
        return True
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    return name.lower().endswith(FORBIDDEN_SUFFIXES)


def _git(*args: str) -> list[str]:
    out = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def is_release_pr(title: str) -> bool:
    """A release PR promotes reviewed work from `dev` to `main`, so it may contain everything.

    GitHub sets GITHUB_HEAD_REF / GITHUB_BASE_REF on pull_request runs; both must match.
    """
    return (
        title.strip().lower().startswith(RELEASE_TAG)
        and os.environ.get("GITHUB_HEAD_REF") == "dev"
        and os.environ.get("GITHUB_BASE_REF") == "main"
    )


# ---------------------------------------------------------------- rules
def check_locked(all_changed: list[str], title: str) -> list[str]:
    """Rule a. `all_changed` includes deletions and both sides of renames."""
    locked = sorted(p for p in all_changed if is_locked(p))
    if not locked:
        return []
    title = title.strip()
    if title.lower().startswith(FOUNDATION_TAG):
        return []
    if is_release_pr(title):
        return []
    other = sorted(p for p in all_changed if not is_locked(p))
    errors: list[str] = []
    if other:
        errors.append(
            "Locked paths changed together with other code. Locked changes must be a separate PR.\n"
            f"    locked: {', '.join(locked)}\n"
            f"    other:  {', '.join(other)}"
        )
    elif not title.lower().startswith(LOCKED_TAGS):
        errors.append(
            f"This PR changes locked paths ({', '.join(locked)}) but its title does not start with "
            f"one of {', '.join(LOCKED_TAGS)}. Retitle it, e.g. '[tests] add lock boundary case'."
        )
    return errors


def check_no_data(present_files: list[str]) -> list[str]:
    """Rule b. `present_files` are added/changed (or tracked, in scan mode) files."""
    bad = sorted(p for p in present_files if is_forbidden_data(p))
    if not bad:
        return []
    return ["Client data / secrets must never be committed (public repo). Remove: " + ", ".join(bad)]


def find_forbidden_markers(text: str) -> list[str]:
    return [pat for pat in FORBIDDEN_TEST_PATTERNS if pat in text]


def check_no_skips(present_files: list[str], read=None) -> list[str]:
    """Rule c. Scan full content of test files for skip / xfail / focus markers."""
    read = read or (lambda p: (ROOT / p).read_text(encoding="utf-8", errors="replace"))
    errors = []
    for p in sorted(present_files):
        if not is_test_file(p):
            continue
        try:
            text = read(p)
        except (FileNotFoundError, IsADirectoryError):
            continue
        hits = find_forbidden_markers(text)
        if hits:
            errors.append(f"{p}: forbidden test marker(s) {', '.join(hits)} (no skip/xfail/.only)")
    return errors


def check_coverage(ci_text: str | None) -> list[str]:
    """Rule d."""
    if ci_text is None:
        return [f"{CI_WORKFLOW} is missing."]
    values = [float(v) for v in COV_RE.findall(ci_text)]
    if not values:
        return [f"{CI_WORKFLOW} no longer sets --cov-fail-under (must be >= {MIN_COVERAGE:g})."]
    low = [v for v in values if v < MIN_COVERAGE]
    if low:
        return [f"--cov-fail-under lowered to {min(low):g} in {CI_WORKFLOW} (must be >= {MIN_COVERAGE:g})."]
    return []


def _read_ci() -> str | None:
    path = ROOT / CI_WORKFLOW
    return path.read_text(encoding="utf-8") if path.exists() else None


# ---------------------------------------------------------------- modes
def run_pr(base: str, title: str) -> tuple[list[str], list[str]]:
    diff = f"{base}...HEAD"
    all_changed = _git("diff", "--name-only", "--no-renames", diff)
    present = _git("diff", "--name-only", "--no-renames", "--diff-filter=ACMRT", diff)
    summary = [
        f"mode: PR (diff {diff})",
        f"title: {title!r}",
        f"files changed: {len(all_changed)} (locked: {sum(is_locked(p) for p in all_changed)})",
        f"test files scanned: {sum(is_test_file(p) for p in present)}",
    ]
    errors = (
        check_locked(all_changed, title)
        + check_no_data(present)
        + check_no_skips(present)
        + check_coverage(_read_ci())
    )
    return summary, errors


def run_scan() -> tuple[list[str], list[str]]:
    tracked = _git("ls-files")
    summary = [
        "mode: scan (all tracked files)",
        f"files checked: {len(tracked)}",
        f"test files scanned: {sum(is_test_file(p) for p in tracked)}",
    ]
    errors = check_no_data(tracked) + check_no_skips(tracked) + check_coverage(_read_ci())
    return summary, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--base", help="base ref for PR mode, e.g. origin/main")
    group.add_argument("--scan", action="store_true", help="scan the whole tracked tree (push mode)")
    args = ap.parse_args(argv)

    try:
        if args.scan:
            summary, errors = run_scan()
        else:
            summary, errors = run_pr(args.base, os.environ.get("PR_TITLE", ""))
    except subprocess.CalledProcessError as exc:
        print(f"integrity: git failed: {exc.stderr or exc}", file=sys.stderr)
        return 2

    print("Integrity check")
    for line in summary:
        print(f"  {line}")
    print("  rules: a=locked paths separate PR, b=no data/secrets, c=no skip/xfail/.only, d=coverage>=90")
    if errors:
        print(f"\nFAILED ({len(errors)} problem(s)):")
        for err in errors:
            print(f"  - {err}")
        print("\nSee scripts/ci/README.md for the rules.")
        return 1
    print("\nOK: all integrity rules passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
