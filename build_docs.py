#!/usr/bin/env python3
"""Pull markdown docs from usr-wwelsh's public repos and build a botdocs site.

Clones nothing but the docs: git partial clone (--filter=blob:none) +
sparse-checkout scoped to *.md, so no source trees are pulled to disk.
"""
import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

USERNAME = "usr-wwelsh"
HERE = Path(__file__).resolve().parent
EXCLUDES_FILE = HERE / "repo-excludes.json"
CONFIG_FILE = HERE / "botdocs.config.json"
HOME_FILE = HERE / "home.md"
CSS_FILE = HERE / "custom.css"
STATIC_DIR = HERE / "static"
CLONE_DIR = HERE / ".clones"
SRC_DIR = HERE / "site-src"
OUTPUT_DIR = HERE / "output"
BASE_URL = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))["baseUrl"]
DESCRIPTION_MAX = 160
MIN_PROSE = 40


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


EXCLUDED_DIRS = {".git", "skills", "test-docs", "fixtures", "eval"}
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


def extract_description(md: str) -> str:
    front = re.match(r"---\n(.*?)\n---\n", md, re.DOTALL)
    if front:
        field = re.search(r"^description:\s*(.+)$", front.group(1), re.MULTILINE)
        if field:
            return field.group(1).strip()
        md = md[front.end():]
    for block in re.split(r"\n\s*\n", md):
        block = block.strip()
        if not block or block[0] in "#<|>-*!" or block.startswith(("```", "[![")) or re.match(r"\d+\.", block):
            continue
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", block)
        text = re.sub(r"[*_`]", "", text)
        text = " ".join(text.split())
        if len(text) < MIN_PROSE:
            continue
        if len(text) > DESCRIPTION_MAX:
            text = text[: DESCRIPTION_MAX - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-") + "\u2026"
        return text
    return ""


def dedupe_title(match: re.Match) -> str:
    head, title, tail = match.groups()
    half, sep, rest = title.partition(" - ")
    return f"{head}{half if sep and rest == half else title}{tail}"


def enhance_html(page: str, description: str, base_url: str) -> str:
    if description:
        content = html.escape(description, quote=True)
        page = re.sub(r'(<meta name="description" content=")[^"]*', lambda m: m.group(1) + content, page)
        page = re.sub(r'(<meta property="og:description" content=")[^"]*', lambda m: m.group(1) + content, page)
    page = re.sub(r"(<title>)([^<]*)(</title>)", dedupe_title, page)
    page = re.sub(r'(<meta property="og:title" content=")([^"]*)(")', dedupe_title, page)
    page = page.replace('<meta name="twitter:card" content="summary">', '<meta name="twitter:card" content="summary_large_image">')
    root = re.search(r'<meta name="botdocs-root" content="([^"]*)"', page)
    icon = (root.group(1) if root else "./") + "favicon.svg"
    image = f"{base_url}og.png"
    extra = (
        f'  <meta property="og:image" content="{image}">\n'
        f'  <meta name="twitter:image" content="{image}">\n'
        f'  <link rel="icon" href="{icon}" type="image/svg+xml">\n'
    )
    return page.replace("</head>", extra + "</head>", 1)


def enhance_site(site_dir: Path, output_dir: Path, base_url: str, static_dir: Path = STATIC_DIR) -> None:
    for page in sorted(output_dir.rglob("*.html")):
        rel = page.relative_to(output_dir)
        source = site_dir / ("README.md" if rel.as_posix() == "index.html" else rel.with_suffix(".md"))
        description = extract_description(source.read_text(encoding="utf-8")) if source.is_file() else ""
        page.write_text(enhance_html(page.read_text(encoding="utf-8"), description, base_url), encoding="utf-8")
    if static_dir.is_dir():
        for asset in static_dir.iterdir():
            shutil.copy(asset, output_dir / asset.name)


def fingerprint(site_dir: Path, *extra: Path) -> str:
    h = hashlib.sha256()
    entries = [(p.relative_to(site_dir).as_posix(), p) for p in sorted(site_dir.rglob("*")) if p.is_file()]
    entries += [(f"extra/{p.name}", p) for p in extra]
    for name, path in entries:
        h.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def missing_pages(site_dir: Path, output_dir: Path) -> list[str]:
    expected = ["index.html"] + sorted(
        p.relative_to(site_dir).with_suffix(".html").as_posix() for p in site_dir.rglob("*.md")
    )
    return [page for page in expected if not (output_dir / page).is_file()]


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

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    subprocess.run(
        ["botdocs", str(SRC_DIR), "-o", str(OUTPUT_DIR), "-c", str(CONFIG_FILE)],
        check=True,
    )
    missing = missing_pages(SRC_DIR, OUTPUT_DIR)
    if missing:
        print("Build incomplete, missing pages:", *missing, sep="\n  ", file=sys.stderr)
        return 1
    enhance_site(SRC_DIR, OUTPUT_DIR, BASE_URL)
    (OUTPUT_DIR / "fingerprint.txt").write_text(
        fingerprint(SRC_DIR, CONFIG_FILE, CSS_FILE, *sorted(STATIC_DIR.glob("*")), Path(__file__)) + "\n", encoding="utf-8",
    )
    print(f"\nSite built at {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
