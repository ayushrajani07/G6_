#!/usr/bin/env python
"""Interactive git push menu (Python variant).

Mirrors functionality of PowerShell script `git_push_menu.ps1`.

Options:
  1. Push to main (default)
  2. Push current branch
  3. Pull --rebase then push (current branch)
  4. Force-with-lease push (current branch)
  5. Create lightweight tag then push (requires --tag)
  6. Push existing tag (requires --tag)
  7. Push all tags
  8. Status & ahead/behind summary
  9. Dry-run push (current branch)
 10. Fetch --prune
  0. Exit

CLI flags for non-interactive use:
  --option <n>  Select menu option programmatically
  --tag <name>  Tag name for options 5 or 6
  --message <m> Auto-commit staged + unstaged changes before action
  --yes         Auto-confirm prompts (e.g., auto-commit uncommitted changes)

Exit codes:
  0 success
  1 generic failure
  2 invalid option or precondition failure

Requires git in PATH.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# ---------------- Helpers ---------------- #

def run(cmd: list[str], check: bool = True, capture: bool = False, silent: bool = False) -> subprocess.CompletedProcess:
    if not silent:
        print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)

def git_output(args: list[str], default: str = "") -> str:
    try:
        cp = run(["git", *args], capture=True)
        return cp.stdout.strip()
    except subprocess.CalledProcessError:
        return default

def ensure_repo() -> None:
    if not os.path.isdir('.git'):
        print("ERROR: Not inside a git repository root.", file=sys.stderr)
        sys.exit(1)

def get_current_branch() -> str:
    br = git_output(["rev-parse", "--abbrev-ref", "HEAD"], default="")
    if not br:
        print("ERROR: Unable to determine current branch.", file=sys.stderr)
        sys.exit(1)
    return br

def get_status_porcelain() -> list[str]:
    out = git_output(["status", "--porcelain"], default="")
    return [l for l in out.splitlines() if l.strip()]

def ahead_behind(branch: str) -> str:
    # Fetch remote branch quietly
    try:
        run(["git", "fetch", "origin", branch], check=False, capture=True, silent=True)
    except Exception:
        pass
    counts = git_output(["rev-list", "--left-right", "--count", f"origin/{branch}...{branch}"], default="")
    if counts:
        parts = counts.split()
        if len(parts) == 2:
            behind, ahead = parts
            return f"Behind:{behind} Ahead:{ahead}"
    return "(ahead/behind n/a)"

def auto_commit(message: str) -> None:
    status = get_status_porcelain()
    if not status:
        print("No changes to commit (skip auto-commit).")
        return
    run(["git", "add", "-A"], check=True)
    try:
        run(["git", "commit", "-m", message], check=True)
    except subprocess.CalledProcessError:
        print("Auto-commit did not create a commit (possibly nothing to commit).")

# ---------------- Actions ---------------- #

def require_clean_or_commit(auto_confirm: bool) -> None:
    st = get_status_porcelain()
    if not st:
        return
    print("Uncommitted changes detected:")
    for line in st[:20]:
        print("  ", line)
    if len(st) > 20:
        print(f"  ... ({len(st)-20} more)")
    if auto_confirm:
        print("--yes supplied: auto committing before push.")
        auto_commit("auto: staging before push")
        return
    resp = input("Stage & commit automatically? (y/N): ").strip().lower()
    if resp.startswith('y'):
        auto_commit("auto: staging before push")
    else:
        print("Aborting due to uncommitted changes.")
        sys.exit(2)

def act_push_main(auto_confirm: bool) -> None:
    require_clean_or_commit(auto_confirm)
    run(["git", "fetch", "origin", "main"], check=False)
    run(["git", "rebase", "origin/main"], check=False)
    run(["git", "push", "origin", "HEAD:main"], check=True)


def act_push_current(branch: str, auto_confirm: bool) -> None:
    require_clean_or_commit(auto_confirm)
    run(["git", "push", "origin", branch], check=True)


def act_pull_rebase_push(branch: str, auto_confirm: bool) -> None:
    require_clean_or_commit(auto_confirm)
    run(["git", "fetch", "origin", branch], check=False)
    run(["git", "rebase", f"origin/{branch}"], check=False)
    run(["git", "push", "origin", branch], check=True)


def act_force_with_lease(branch: str, auto_confirm: bool) -> None:
    require_clean_or_commit(auto_confirm)
    run(["git", "push", "--force-with-lease", "origin", branch], check=True)


def act_create_tag_and_push(tag: str, auto_confirm: bool) -> None:
    if not tag:
        print("ERROR: --tag required for create tag option", file=sys.stderr)
        sys.exit(2)
    require_clean_or_commit(auto_confirm)
    run(["git", "tag", tag], check=True)
    run(["git", "push", "origin", tag], check=True)


def act_push_existing_tag(tag: str) -> None:
    if not tag:
        print("ERROR: --tag required for push existing tag option", file=sys.stderr)
        sys.exit(2)
    run(["git", "push", "origin", tag], check=True)


def act_push_all_tags() -> None:
    run(["git", "push", "origin", "--tags"], check=True)


def act_status(branch: str) -> None:
    run(["git", "status"], check=True)
    print(f"Branch {branch} {ahead_behind(branch)}")


def act_dry_run(branch: str) -> None:
    run(["git", "push", "--dry-run", "origin", branch], check=True)


def act_fetch_prune() -> None:
    run(["git", "fetch", "--prune", "origin"], check=True)

# ---------------- Menu ---------------- #

MENU = {
    1: ("Push to main", act_push_main),
    2: ("Push current branch", act_push_current),
    3: ("Pull --rebase then push", act_pull_rebase_push),
    4: ("Force-with-lease push", act_force_with_lease),
    5: ("Create tag then push", act_create_tag_and_push),
    6: ("Push existing tag", act_push_existing_tag),
    7: ("Push all tags", act_push_all_tags),
    8: ("Status & ahead/behind", act_status),
    9: ("Dry-run push", act_dry_run),
    10: ("Fetch --prune", lambda *_: act_fetch_prune()),
    0: ("Exit", None),
}


def print_menu():
    print("\nGit Push Menu (Python)")
    for k in sorted(MENU.keys()):
        if k == 0:
            print("  0. Exit")
        else:
            print(f"  {k:2d}. {MENU[k][0]}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Interactive git push menu (Python)")
    ap.add_argument('--option', type=int, help='Menu option (non-interactive)')
    ap.add_argument('--tag', type=str, help='Tag name for tag-related options')
    ap.add_argument('--message', type=str, help='Auto-commit message (commit staged + unstaged before action)')
    ap.add_argument('--yes', action='store_true', help='Auto-confirm prompts (e.g., commit uncommitted changes)')
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    ensure_repo()
    args = parse_args(argv)
    branch = get_current_branch()

    if args.message:
        print(f"Auto-commit attempt with message: {args.message}")
        auto_commit(args.message)

    option: int | None = args.option
    if option is None:
        print_menu()
        raw = input("Select option (default 1): ").strip()
        if not raw:
            option = 1
        else:
            try:
                option = int(raw)
            except ValueError:
                print("Invalid numeric option.")
                return 2

    if option not in MENU:
        print(f"Unknown option: {option}")
        return 2
    if option == 0:
        print("Exit.")
        return 0

    label, func = MENU[option]
    print(f"== {label} ==")
    try:
        if option in {1}:
            func(args.yes)  # push to main
        elif option in {2,3,4,9}:  # need branch + maybe yes
            func(branch, args.yes)
        elif option == 5:  # create tag then push
            func(args.tag, args.yes)
        elif option == 6:  # push existing tag
            func(args.tag)
        elif option == 7:  # push all tags
            func()
        elif option == 8:  # status
            func(branch)
        elif option == 10:  # fetch prune
            func()
        else:
            print("Unhandled option mapping (internal logic error).")
            return 2
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}", file=sys.stderr)
        return 1

    print("Done.")
    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
