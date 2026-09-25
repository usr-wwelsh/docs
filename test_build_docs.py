import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_docs
from build_docs import (
    add_repo_link,
    filter_repos,
    list_repos,
    local_repos,
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


if __name__ == "__main__":
    unittest.main()
