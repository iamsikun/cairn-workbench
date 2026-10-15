import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from cairn_catalog import publisher_archives


class PublisherArchiveTests(unittest.TestCase):
    def test_temporary_connection_failure_retries_the_same_article(self):
        url = "https://jmlr.org/papers/v1/example.html"
        response = Mock(status_code=200, text="verified article HTML")
        with (
            patch.object(
                publisher_archives.CLIENT.session,
                "get",
                side_effect=[requests.ConnectionError("temporary DNS failure"), response],
            ) as get,
            patch.object(publisher_archives.time, "sleep"),
        ):
            self.assertEqual(publisher_archives.get(url), "verified article HTML")
        self.assertEqual(get.call_count, 2)
        self.assertTrue(all(call.args == (url,) for call in get.call_args_list))

    def test_persistent_connection_failure_remains_a_failure_after_bounded_retries(self):
        with (
            patch.object(
                publisher_archives.CLIENT.session,
                "get",
                side_effect=requests.ConnectionError("DNS unavailable"),
            ) as get,
            patch.object(publisher_archives.time, "sleep"),
        ):
            with self.assertRaisesRegex(requests.ConnectionError, "DNS unavailable"):
                publisher_archives.get("https://jmlr.org/papers/v1/example.html")
        self.assertEqual(get.call_count, 8)

    def test_abstract_excludes_download_links_and_footer(self):
        source = '<h3>Abstract</h3><p class="abstract">An original abstract with <em>markup</em>.</p><p>[pdf] copyright footer</p>'
        self.assertEqual(
            publisher_archives.abstract_text(source), "An original abstract with markup."
        )

    def test_legacy_unquoted_links_and_explicit_article_number(self):
        toc = "<dt>A paper<dd><b><i>Jane Scholar, John Author</i></b><a href=example.html>[abs]</a></dd>"
        articles = publisher_archives.toc_articles(toc, "https://jmlr.org/papers/v1/")
        url = "https://jmlr.org/papers/v1/example.html"
        self.assertEqual(articles[url]["authors"], ["Jane Scholar", "John Author"])
        source = '<meta name="citation_title" content="A paper"><meta name="citation_publication_date" content="2026/10"><meta name="citation_issue" content="205"><meta name="citation_volume" content="27"><p class="abstract">Original abstract.</p>'
        record = publisher_archives.record_for(url, source, articles[url], 27)
        self.assertEqual(record["article_number"], "205")
        self.assertIsNone(record["issue"])
        self.assertEqual(record["date"], "2026-10")

    def test_homepage_current_volume_and_new_article_survive_cached_tocs(self):
        pages = {
            "https://jmlr.org/papers/": '<a href="v1">Volume 1</a>',
            "https://www.jmlr.org/": '<a href="/papers/v2/">Volume 2</a>',
        }

        def toc(number):
            return f'<dt>Paper {number}<dd><b><i>Jane Scholar</i></b><a href="paper{number}.html">[abs]</a></dd>'

        def article(number, volume):
            return f'<meta name="citation_title" content="Paper {number}"><meta name="citation_volume" content="{volume}"><meta name="citation_publication_date" content="2026"><p class="abstract">Original abstract {number}.</p>'

        for volume in [1, 2]:
            pages[f"https://jmlr.org/papers/v{volume}/"] = toc(volume)
            pages[f"https://jmlr.org/papers/v{volume}/paper{volume}.html"] = article(volume, volume)
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(publisher_archives, "get", side_effect=lambda url: pages[url]),
            patch.object(publisher_archives.time, "sleep"),
        ):
            root = Path(temp)
            publisher_archives.harvest_jmlr(root)
            pages["https://jmlr.org/papers/v2/"] += toc(3)
            pages["https://jmlr.org/papers/v2/paper3.html"] = article(3, 2)
            publisher_archives.harvest_jmlr(root)
            state = json.loads((root / "raw/journal_archive/jmlr/state.json").read_text())
        self.assertEqual(state["latest_volume"], 2)
        self.assertEqual(state["retrieved"], 3)
        self.assertTrue(state["complete"])


if __name__ == "__main__":
    unittest.main()
