import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_docs
from build_docs import (
    absolutize_images,
    add_repo_link,
    enhance_html,
    enhance_site,
    extract_description,
    filter_repos,
    fingerprint,
    list_repos,
    local_repos,
    missing_pages,
    stage_docs,
    update_clone,
    write_index,
)


def _run(*args: str) -> None:
    subprocess.run(args, check=True, capture_output=True, text=True)


class FilterReposTests(unittest.TestCase):
    def test_excludes_named_repos(self):
        repos = [
            {"name": "keep", "fork": False, "private": False},
            {"name": "skip", "fork": False, "private": False},
        ]
        result = filter_repos(repos, {"skip"})
        self.assertEqual([r["name"] for r in result], ["keep"])

    def test_excludes_forks(self):
        repos = [{"name": "a", "fork": True, "private": False}]
        self.assertEqual(filter_repos(repos, set()), [])

    def test_excludes_private(self):
        repos = [{"name": "a", "fork": False, "private": True}]
        self.assertEqual(filter_repos(repos, set()), [])

    def test_keeps_public_non_excluded(self):
        repos = [{"name": "a", "fork": False, "private": False}]
        self.assertEqual(filter_repos(repos, set()), repos)


class ListReposTests(unittest.TestCase):
    def test_queries_public_user_endpoint_not_authenticated_user(self):
        fake = subprocess.CompletedProcess([], 0, stdout='{"name": "a", "clone_url": "u", "fork": false, "private": false}\n')
        with patch("build_docs.subprocess.run", return_value=fake) as run:
            repos = list_repos()
        self.assertIn("users/usr-wwelsh/repos?type=owner&per_page=100", run.call_args.args[0])
        self.assertEqual(repos, [{"name": "a", "clone_url": "u", "fork": False, "private": False}])


class FingerprintTests(unittest.TestCase):
    def _tree(self, root: Path, files: dict[str, str]) -> Path:
        for rel, content in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(content, encoding="utf-8")
        return root

    def test_same_inputs_give_same_fingerprint(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            files = {"repo/README.md": "x", "repo/docs/guide.md": "y"}
            self.assertEqual(
                fingerprint(self._tree(Path(a), files)),
                fingerprint(self._tree(Path(b), files)),
            )

    def test_content_change_changes_fingerprint(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertNotEqual(
                fingerprint(self._tree(Path(a), {"repo/README.md": "x"})),
                fingerprint(self._tree(Path(b), {"repo/README.md": "z"})),
            )

    def test_rename_changes_fingerprint(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertNotEqual(
                fingerprint(self._tree(Path(a), {"repo/a.md": "x"})),
                fingerprint(self._tree(Path(b), {"repo/b.md": "x"})),
            )

    def test_extra_file_change_changes_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            site = self._tree(tmp / "site", {"repo/README.md": "x"})
            css = tmp / "custom.css"
            css.write_text("a{}", encoding="utf-8")
            before = fingerprint(site, css)
            css.write_text("b{}", encoding="utf-8")
            self.assertNotEqual(before, fingerprint(site, css))


class MissingPagesTests(unittest.TestCase):
    def _build(self, tmp: Path, md: list[str], html: list[str]) -> tuple[Path, Path]:
        src, out = tmp / "src", tmp / "out"
        for rel in md:
            (src / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / rel).write_text("x", encoding="utf-8")
        for rel in html:
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_text("x", encoding="utf-8")
        return src, out

    def test_complete_build_has_nothing_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = self._build(
                Path(tmp),
                ["README.md", "repo/README.md", "repo/docs/guide.md"],
                ["index.html", "README.html", "repo/README.html", "repo/docs/guide.html"],
            )
            self.assertEqual(missing_pages(src, out), [])

    def test_reports_page_botdocs_did_not_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = self._build(
                Path(tmp),
                ["README.md", "repo/README.md"],
                ["index.html", "README.html"],
            )
            self.assertEqual(missing_pages(src, out), ["repo/README.html"])

    def test_reports_missing_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = self._build(Path(tmp), ["README.md"], ["README.html"])
            self.assertEqual(missing_pages(src, out), ["index.html"])


class WriteIndexTests(unittest.TestCase):
    def test_uses_custom_home_page_as_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            home = tmp / "home.md"
            home.write_text("# custom home\n", encoding="utf-8")
            staging_dir = tmp / "site"
            staging_dir.mkdir()
            write_index(home, staging_dir)
            content = (staging_dir / "README.md").read_text(encoding="utf-8")

        self.assertEqual(content, "# custom home\n")


class StageDocsTests(unittest.TestCase):
    def test_copies_every_markdown_file_preserving_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "clone"
            staging_dir = Path(tmp) / "staging"
            (clone_dir / "docs" / "sub").mkdir(parents=True)
            (clone_dir / "src").mkdir()
            (clone_dir / "README.md").write_text("root")
            (clone_dir / "docs" / "guide.md").write_text("guide")
            (clone_dir / "docs" / "sub" / "nested.md").write_text("nested")
            (clone_dir / "src" / "CONTRIBUTING.md").write_text("contrib")

            result = stage_docs({"name": "myrepo"}, clone_dir, staging_dir)

            self.assertTrue(result)
            target = staging_dir / "myrepo"
            self.assertTrue((target / "README.md").exists())
            self.assertEqual((target / "docs" / "guide.md").read_text(), "guide")
            self.assertEqual(
                (target / "docs" / "sub" / "nested.md").read_text(), "nested"
            )
            self.assertEqual(
                (target / "src" / "CONTRIBUTING.md").read_text(), "contrib"
            )

    def test_ignores_markdown_inside_git_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "clone"
            staging_dir = Path(tmp) / "staging"
            (clone_dir / ".git").mkdir(parents=True)
            (clone_dir / ".git" / "COMMIT_EDITMSG.md").write_text("noise")

            result = stage_docs({"name": "myrepo"}, clone_dir, staging_dir)

            self.assertFalse(result)
            self.assertFalse((staging_dir / "myrepo").exists())

    def test_returns_false_when_no_markdown_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "clone"
            clone_dir.mkdir()
            staging_dir = Path(tmp) / "staging"

            result = stage_docs({"name": "myrepo"}, clone_dir, staging_dir)

            self.assertFalse(result)

    def test_excludes_claude_md_and_please_read_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "clone"
            staging_dir = Path(tmp) / "staging"
            clone_dir.mkdir()
            (clone_dir / "README.md").write_text("root")
            (clone_dir / "CLAUDE.md").write_text("agent instructions")
            (clone_dir / "PLEASE_READ.md").write_text("maintainer note")
            (clone_dir / "AGENTS.md").write_text("agent instructions")

            stage_docs({"name": "myrepo"}, clone_dir, staging_dir)

            target = staging_dir / "myrepo"
            self.assertTrue((target / "README.md").exists())
            self.assertFalse((target / "CLAUDE.md").exists())
            self.assertFalse((target / "PLEASE_READ.md").exists())
            self.assertFalse((target / "AGENTS.md").exists())

    def test_excludes_skills_directory_at_any_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "clone"
            staging_dir = Path(tmp) / "staging"
            (clone_dir / "skills" / "foo").mkdir(parents=True)
            (clone_dir / "nested" / "skills").mkdir(parents=True)
            (clone_dir / "README.md").write_text("root")
            (clone_dir / "skills" / "README.md").write_text("skill index")
            (clone_dir / "skills" / "foo" / "SKILL.md").write_text("skill")
            (clone_dir / "nested" / "skills" / "SKILL.md").write_text("nested skill")

            stage_docs({"name": "myrepo"}, clone_dir, staging_dir)

            target = staging_dir / "myrepo"
            self.assertTrue((target / "README.md").exists())
            self.assertFalse((target / "skills").exists())
            self.assertFalse((target / "nested" / "skills").exists())

    def test_excludes_test_docs_and_fixtures_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "clone"
            staging_dir = Path(tmp) / "staging"
            (clone_dir / "test-docs").mkdir(parents=True)
            (clone_dir / "fixtures").mkdir(parents=True)
            (clone_dir / "README.md").write_text("root")
            (clone_dir / "test-docs" / "gfm-test.md").write_text("gfm")
            (clone_dir / "fixtures" / "test-shelter-c.md").write_text("fixture")

            stage_docs({"name": "myrepo"}, clone_dir, staging_dir)

            target = staging_dir / "myrepo"
            self.assertTrue((target / "README.md").exists())
            self.assertFalse((target / "test-docs").exists())
            self.assertFalse((target / "fixtures").exists())

    def test_excludes_eval_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "clone"
            staging_dir = Path(tmp) / "staging"
            (clone_dir / "eval" / "corpus" / "x").mkdir(parents=True)
            (clone_dir / "README.md").write_text("root")
            (clone_dir / "eval" / "corpus" / "x" / "README.md").write_text("corpus")

            stage_docs({"name": "myrepo"}, clone_dir, staging_dir)

            target = staging_dir / "myrepo"
            self.assertTrue((target / "README.md").exists())
            self.assertFalse((target / "eval").exists())


class AddRepoLinkTests(unittest.TestCase):
    def test_inserts_link_after_leading_h1(self):
        content = "# Botdocs\n\nConvert markdown into sites.\n"
        result = add_repo_link(content, "https://github.com/usr-wwelsh/botdocs")

        self.assertEqual(
            result,
            "# Botdocs\n\n"
            "[View on GitHub](https://github.com/usr-wwelsh/botdocs)\n\n"
            "Convert markdown into sites.\n",
        )

    def test_prepends_link_when_no_leading_h1(self):
        content = "Some docs without a heading.\n"
        result = add_repo_link(content, "https://github.com/usr-wwelsh/myrepo")

        self.assertEqual(
            result,
            "[View on GitHub](https://github.com/usr-wwelsh/myrepo)\n\n"
            "Some docs without a heading.\n",
        )


RAW = "https://raw.githubusercontent.com/usr-wwelsh/myrepo/HEAD"


class AbsolutizeImagesTests(unittest.TestCase):
    def test_html_img_src_becomes_raw_url(self):
        result = absolutize_images('<img src="demo1.webp" width="400"/>', "myrepo", "README.md")
        self.assertEqual(result, f'<img src="{RAW}/demo1.webp" width="400"/>')

    def test_markdown_image_becomes_raw_url(self):
        result = absolutize_images("![shot](img/a.png)", "myrepo", "README.md")
        self.assertEqual(result, f"![shot]({RAW}/img/a.png)")

    def test_path_resolves_against_md_file_directory(self):
        result = absolutize_images("![x](../a.png) ![y](./b.png)", "myrepo", "docs/guide/page.md")
        self.assertEqual(result, f"![x]({RAW}/docs/a.png) ![y]({RAW}/docs/guide/b.png)")

    def test_leading_slash_resolves_against_repo_root(self):
        result = absolutize_images("![x](/a.png)", "myrepo", "docs/page.md")
        self.assertEqual(result, f"![x]({RAW}/a.png)")

    def test_absolute_and_data_urls_are_untouched(self):
        content = '![a](https://x.io/a.svg) <img src="//x.io/b.png"> ![c](data:image/png;base64,AAA)'
        self.assertEqual(absolutize_images(content, "myrepo", "README.md"), content)

    def test_title_after_path_is_preserved(self):
        result = absolutize_images('![x](a.png "tip")', "myrepo", "README.md")
        self.assertEqual(result, f'![x]({RAW}/a.png "tip")')

    def test_path_escaping_repo_root_is_untouched(self):
        content = "![x](../../a.png)"
        self.assertEqual(absolutize_images(content, "myrepo", "README.md"), content)


class StageDocsImageTests(unittest.TestCase):
    def test_staged_markdown_has_absolute_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "clone"
            staging_dir = Path(tmp) / "staging"
            (clone_dir / "docs").mkdir(parents=True)
            (clone_dir / "docs" / "a.md").write_text("![x](p.png)")

            stage_docs({"name": "myrepo"}, clone_dir, staging_dir)

            content = (staging_dir / "myrepo" / "docs" / "a.md").read_text()
            self.assertEqual(content, f"![x]({RAW}/docs/p.png)")


class StageDocsRepoLinkTests(unittest.TestCase):
    def test_top_level_readme_gets_repo_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "clone"
            staging_dir = Path(tmp) / "staging"
            clone_dir.mkdir()
            (clone_dir / "README.md").write_text("# Myrepo\n\nBody text.\n")

            stage_docs({"name": "myrepo"}, clone_dir, staging_dir)

            content = (staging_dir / "myrepo" / "README.md").read_text()
            self.assertIn(
                "[View on GitHub](https://github.com/usr-wwelsh/myrepo)", content
            )

    def test_nested_readme_is_left_unlinked(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "clone"
            staging_dir = Path(tmp) / "staging"
            (clone_dir / "docs").mkdir(parents=True)
            (clone_dir / "README.md").write_text("root")
            (clone_dir / "docs" / "README.md").write_text("nested")

            stage_docs({"name": "myrepo"}, clone_dir, staging_dir)

            nested = (staging_dir / "myrepo" / "docs" / "README.md").read_text()
            self.assertEqual(nested, "nested")


class UpdateCloneTests(unittest.TestCase):
    def test_corrects_stale_sparse_checkout_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp) / "origin"
            dest = Path(tmp) / "dest"
            origin.mkdir()
            (origin / "other").mkdir()
            (origin / "README.md").write_text("root")
            (origin / "other" / "extra.md").write_text("extra")
            _run("git", "-C", str(origin), "init", "-q", "--initial-branch=main")
            _run("git", "-C", str(origin), "add", "-A")
            _run(
                "git", "-C", str(origin), "-c", "user.email=a@a", "-c", "user.name=a",
                "commit", "-q", "-m", "init",
            )

            _run(
                "git", "clone", "-q", "--filter=blob:none", "--sparse",
                f"file://{origin}", str(dest),
            )
            _run(
                "git", "-C", str(dest), "sparse-checkout", "set", "--no-cone",
                "/README.md", "/docs/**",
            )
            self.assertFalse((dest / "other" / "extra.md").exists())

            update_clone(dest)

            self.assertTrue((dest / "other" / "extra.md").exists())


class LocalReposTests(unittest.TestCase):
    def test_lists_cached_clone_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp)
            (clone_dir / "a").mkdir()
            (clone_dir / "b").mkdir()
            with patch.object(build_docs, "CLONE_DIR", clone_dir):
                result = local_repos(set())
        self.assertEqual([r["name"] for r in result], ["a", "b"])

    def test_excludes_named_repos(self):
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp)
            (clone_dir / "a").mkdir()
            (clone_dir / "skip").mkdir()
            with patch.object(build_docs, "CLONE_DIR", clone_dir):
                result = local_repos({"skip"})
        self.assertEqual([r["name"] for r in result], ["a"])

    def test_empty_when_no_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "not-there"
            with patch.object(build_docs, "CLONE_DIR", missing):
                self.assertEqual(local_repos(set()), [])


HEAD = """<head>
  <meta name="description" content="GitHub · Portfolio">
  <title>turbolab - usr-wwelsh docs</title>
  <meta property="og:title" content="turbolab - usr-wwelsh docs">
  <meta property="og:description" content="GitHub · Portfolio">
  <meta name="twitter:card" content="summary">
  <meta name="botdocs-root" content="../">
</head>"""
BASE = "https://docs.wwel.sh/"


class ExtractDescriptionTests(unittest.TestCase):
    def test_skips_heading_badges_and_html_to_first_prose(self):
        md = (
            "# tool\n\n[View on GitHub](https://x)\n\n"
            "[![b](https://img/b.svg)](https://x)\n\n"
            "<table><tr><td>x</td></tr></table>\n\n"
            "A self-hosted model server that runs GGUF models on your own hardware.\n\n## Install\n"
        )
        self.assertEqual(
            extract_description(md),
            "A self-hosted model server that runs GGUF models on your own hardware.",
        )

    def test_strips_markdown_links_and_emphasis(self):
        md = "# t\n\nRun **fast** [local models](https://x) with `zero` config and no cloud account needed.\n"
        self.assertEqual(
            extract_description(md),
            "Run fast local models with zero config and no cloud account needed.",
        )

    def test_joins_wrapped_lines(self):
        md = "# t\n\nA tool that does one thing\nand does it well, offline, forever.\n"
        self.assertEqual(extract_description(md), "A tool that does one thing and does it well, offline, forever.")

    def test_truncates_long_text_at_word_boundary_with_ellipsis(self):
        md = "# t\n\n" + "word " * 100
        result = extract_description(md)
        self.assertLessEqual(len(result), 160)
        self.assertTrue(result.endswith("…"))
        self.assertNotIn("wor…", result)

    def test_prefers_front_matter_description(self):
        md = "---\ntitle: x\ndescription: From front matter\n---\n\n# x\n\nBody paragraph that is long enough to be a description.\n"
        self.assertEqual(extract_description(md), "From front matter")

    def test_empty_when_no_prose(self):
        self.assertEqual(extract_description("# t\n\n- a\n- b\n"), "")


class EnhanceHtmlTests(unittest.TestCase):
    def _run(self, head=HEAD, desc="Real description"):
        return enhance_html(head, desc, BASE)

    def test_replaces_both_description_tags(self):
        out = self._run()
        self.assertIn('<meta name="description" content="Real description">', out)
        self.assertIn('<meta property="og:description" content="Real description">', out)
        self.assertNotIn("GitHub · Portfolio", out)

    def test_escapes_description(self):
        out = self._run(desc='a "quoted" <b> & more')
        self.assertIn("a &quot;quoted&quot; &lt;b&gt; &amp; more", out)

    def test_keeps_existing_description_when_none_extracted(self):
        self.assertIn('content="GitHub · Portfolio"', self._run(desc=""))

    def test_adds_absolute_og_and_twitter_image(self):
        out = self._run()
        self.assertIn('<meta property="og:image" content="https://docs.wwel.sh/og.png">', out)
        self.assertIn('<meta name="twitter:image" content="https://docs.wwel.sh/og.png">', out)

    def test_uses_large_twitter_card(self):
        out = self._run()
        self.assertIn('content="summary_large_image"', out)
        self.assertNotIn('content="summary"', out)

    def test_adds_favicon_relative_to_root(self):
        self.assertIn('<link rel="icon" href="../favicon.svg" type="image/svg+xml">', self._run())

    def test_loads_copy_script_relative_to_root(self):
        self.assertIn('<script defer src="../copy.js"></script>', self._run())

    def test_collapses_duplicated_title(self):
        head = HEAD.replace("turbolab - usr-wwelsh docs", "usr-wwelsh docs - usr-wwelsh docs")
        out = self._run(head)
        self.assertIn("<title>usr-wwelsh docs</title>", out)
        self.assertIn('og:title" content="usr-wwelsh docs"', out)

    def test_leaves_distinct_title(self):
        self.assertIn("<title>turbolab - usr-wwelsh docs</title>", self._run())


class EnhanceSiteTests(unittest.TestCase):
    def test_enhances_each_page_from_its_source_and_index_from_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src, out = tmp / "src", tmp / "out"
            (src / "repo").mkdir(parents=True)
            (out / "repo").mkdir(parents=True)
            (src / "README.md").write_text("---\ndescription: Home desc\n---\n# Home\n", encoding="utf-8")
            (src / "repo" / "README.md").write_text(
                "# repo\n\nA long enough paragraph describing what this repo actually does for you.\n", encoding="utf-8",
            )
            for rel in ("index.html", "README.html", "repo/README.html"):
                (out / rel).write_text(HEAD, encoding="utf-8")
            enhance_site(src, out, BASE)
            self.assertIn('content="Home desc"', (out / "index.html").read_text(encoding="utf-8"))
            self.assertIn('content="Home desc"', (out / "README.html").read_text(encoding="utf-8"))
            self.assertIn("what this repo actually does", (out / "repo" / "README.html").read_text(encoding="utf-8"))

    def test_copies_static_assets_into_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src, out, static = tmp / "src", tmp / "out", tmp / "static"
            src.mkdir(); out.mkdir(); static.mkdir()
            (static / "og.png").write_bytes(b"png")
            (src / "README.md").write_text("# h\n", encoding="utf-8")
            (out / "index.html").write_text(HEAD, encoding="utf-8")
            enhance_site(src, out, BASE, static)
            self.assertEqual((out / "og.png").read_bytes(), b"png")


if __name__ == "__main__":
    unittest.main()
