from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from q2_crawler.fixture.server import FixtureServer
from q2_crawler.src.crawler import ProfileCrawler


class CrawlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FixtureServer().start()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.output_path = Path(self.tmpdir.name) / "profiles.jsonl"

    def tearDown(self) -> None:
        self.server.stop()
        self.tmpdir.cleanup()

    def crawl(self):
        return ProfileCrawler(self.server.base_url, self.output_path).crawl()

    def test_duplicate_profile_is_deduped(self) -> None:
        result = self.crawl()
        ids = [profile["id"] for profile in result.profiles]
        self.assertEqual(ids, ["p1", "p2", "p3"])
        self.assertEqual(len(ids), len(set(ids)))
        lines = [json.loads(line) for line in self.output_path.read_text().splitlines()]
        self.assertEqual([line["id"] for line in lines], ids)
        self.assertTrue(any(log["event"] == "duplicate_profile" and log["profile_id"] == "p2" for log in result.logs))

    def test_429_and_401_are_retried_with_refresh(self) -> None:
        result = self.crawl()
        retry_reasons = [log["reason"] for log in result.logs if log["event"] == "retry"]
        self.assertIn("401_session_expired", retry_reasons)
        self.assertIn("429_rate_limited", retry_reasons)
        self.assertTrue(any(log["event"] == "session_refreshed" for log in result.logs))

    def test_cursor_loop_stops_safely_and_logs_invalid_schema(self) -> None:
        result = self.crawl()
        self.assertEqual(result.stop_reason, "cursor_loop")
        self.assertTrue(any(log["event"] == "alert" and log["reason"] == "cursor_loop" for log in result.logs))
        self.assertTrue(any(log["event"] == "validation_error" and log["error"] == "missing_name" for log in result.logs))
        self.assertTrue(any(log["event"] == "page_done" and log.get("next_cursor") == "page2" for log in result.logs))

    def test_fixture_serves_load_more_page(self) -> None:
        with urlopen(self.server.base_url, timeout=5) as response:
            html = response.read().decode("utf-8")
        self.assertIn("Load more", html)
        self.assertIn("button.replaceWith(next)", html)

    def test_empty_next_cursor_ends_normally(self) -> None:
        crawler = ProfileCrawler(self.server.base_url, self.output_path)
        crawler._request_json = lambda path, cursor: {"profiles": [], "next_cursor": ""}
        result = crawler.crawl()
        self.assertEqual(result.stop_reason, "end_of_results")
        self.assertEqual(len([log for log in result.logs if log["event"] == "page_fetch"]), 1)

    def test_missing_page_schema_stops_without_writing_invalid_jsonl(self) -> None:
        crawler = ProfileCrawler(self.server.base_url, self.output_path)
        crawler._request_json = lambda path, cursor: {"profiles": []}
        result = crawler.crawl()
        self.assertEqual(result.stop_reason, "schema_error")
        self.assertTrue(any(log["event"] == "alert" and log["reason"] == "schema_error" for log in result.logs))
        self.assertEqual(self.output_path.read_text(), "")

    def test_rate_limit_retry_has_budget(self) -> None:
        crawler = ProfileCrawler(self.server.base_url, self.output_path)
        attempts = []

        def always_limited(path, cursor):
            attempts.append(cursor)
            raise HTTPError(self.server.base_url, 429, "limited", {"Retry-After": "0"}, None)

        crawler._request_json = always_limited
        with self.assertRaisesRegex(RuntimeError, "retry budget exhausted"):
            crawler.crawl()
        self.assertEqual(len(attempts), 4)

    def test_retry_after_seconds_are_obeyed(self) -> None:
        crawler = ProfileCrawler(self.server.base_url, self.output_path)
        attempts = []

        def limited_once(path, cursor):
            attempts.append(cursor)
            if len(attempts) == 1:
                raise HTTPError(self.server.base_url, 429, "limited", {"Retry-After": "2"}, None)
            return {"profiles": [], "next_cursor": ""}

        crawler._request_json = limited_once
        with patch("q2_crawler.src.crawler.time.sleep") as sleep:
            result = crawler.crawl()
        sleep.assert_called_once_with(2.0)
        self.assertEqual(result.stop_reason, "end_of_results")


if __name__ == "__main__":
    unittest.main()
