#!/usr/bin/env python3
"""Pull markdown docs from usr-wwelsh's public repos and build a botdocs site.

Clones nothing but the docs: git partial clone (--filter=blob:none) +
sparse-checkout scoped to *.md, so no source trees are pulled to disk.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

USERNAME = "usr-wwelsh"
HERE = Path(__file__).resolve().parent
EXCLUDES_FILE = HERE / "repo-excludes.json"
CONFIG_FILE = HERE / "botdocs.config.json"
HOME_FILE = HERE / "home.md"
CLONE_DIR = HERE / ".clones"
SRC_DIR = HERE / "site-src"
OUTPUT_DIR = HERE / "output"


def load_excludes() -> set[str]:
    if not EXCLUDES_FILE.exists():
        return set()
    return set(json.loads(EXCLUDES_FILE.read_text(encoding="utf-8")))


def list_repos() -> list[dict]:
    proc = subprocess.run(
        [
            "gh", "api", f"users/{USERNAME}/repos?type=owner&per_page=100", "--paginate",
            "--jq", ".[] | {name, clone_url, fork, private}",
        ],
        capture_output=True, text=True, check=True,
    )
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def filter_repos(repos: list[dict], excludes: set[str]) -> list[dict]:
    return [
        r for r in repos
        if not r["fork"] and not r["private"] and r["name"] not in excludes
    ]


def apply_sparse_checkout(dest: Path) -> None:
    subprocess.run(
        ["git", "-C", str(dest), "sparse-checkout", "set", "--no-cone", "*.md"],
        check=True,
    )


def sparse_clone(repo: dict, dest: Path) -> None:
    subprocess.run(
        [
            "git", "clone", "--quiet", "--depth", "1",
            "--filter=blob:none", "--sparse",
            repo["clone_url"], str(dest),
        ],
        check=True,
    )
    apply_sparse_checkout(dest)


def is_cloned(dest: Path) -> bool:
    return (dest / ".git").exists()


def update_clone(dest: Path) -> None:
    apply_sparse_checkout(dest)
    subprocess.run(
        ["git", "-C", str(dest), "fetch", "--quiet", "--depth", "1", "origin"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(dest), "reset", "--quiet", "--hard", "FETCH_HEAD"],
        check=True,
    )


def fetch_repo(repo: dict, dest: Path) -> None:
    if is_cloned(dest):
        update_clone(dest)
    else:
        sparse_clone(repo, dest)


def local_repos(excludes: set[str]) -> list[dict]:
    if not CLONE_DIR.exists():
        return []
    return [
        {"name": d.name}
        for d in sorted(CLONE_DIR.iterdir())
        if d.is_dir() and d.name not in excludes
    ]


EXCLUDED_DIRS = {".git", "skills"}
EXCLUDED_FILENAMES = {"CLAUDE.md", "PLEASE_READ.md", "AGENTS.md"}


def add_repo_link(content: str, url: str) -> str:
    link = f"[View on GitHub]({url})"
    if content.startswith("# "):
        heading, _, rest = content.partition("\n")
        return f"{heading}\n\n{link}\n\n{rest.lstrip(chr(10))}"
    return f"{link}\n\n{content}"


def stage_docs(repo: dict, clone_dir: Path, staging_dir: Path) -> bool:
    md_files = [
        p for p in clone_dir.rglob("*.md")
        if not EXCLUDED_DIRS & set(p.relative_to(clone_dir).parts)
        and p.name not in EXCLUDED_FILENAMES
    ]
    if not md_files:
        return False

    target = staging_dir / repo["name"]
    for src in md_files:
        dest = target / src.relative_to(clone_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)

    readme = target / "README.md"
    if readme.exists():
        url = f"https://github.com/{USERNAME}/{repo['name']}"
        readme.write_text(add_repo_link(readme.read_text(encoding="utf-8"), url), encoding="utf-8")
    return True


def write_index(home: Path, staging_dir: Path) -> None:
    shutil.copy(home, staging_dir / "README.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-clone", action="store_true",
        help="reuse .clones/ as-is; no GitHub API call, no git fetch",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    excludes = load_excludes()

    if args.skip_clone:
        repos = local_repos(excludes)
        if not repos:
            print("No cached clones in .clones/ — run without --skip-clone first.", file=sys.stderr)
            return 1
    else:
        repos = filter_repos(list_repos(), excludes)
        if not repos:
            print("No repos to document.", file=sys.stderr)
            return 1

    if SRC_DIR.exists():
        shutil.rmtree(SRC_DIR)
    SRC_DIR.mkdir(parents=True)
    CLONE_DIR.mkdir(parents=True, exist_ok=True)

    for repo in repos:
        dest = CLONE_DIR / repo["name"]
        if not args.skip_clone:
            fetch_repo(repo, dest)
        staged = stage_docs(repo, dest, SRC_DIR)
        print(f"{'->' if staged else '  (skip, no docs)'} {repo['name']}")

    write_index(HOME_FILE, SRC_DIR)

    subprocess.run(
        ["botdocs", str(SRC_DIR), "-o", str(OUTPUT_DIR), "-c", str(CONFIG_FILE)],
        check=True,
    )
    print(f"\nSite built at {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
