from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class CrawlResult:
    profiles: list[dict[str, Any]]
    logs: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = ""


class ProfileCrawler:
    def __init__(self, base_url: str, output_path: str | Path, max_pages: int = 3) -> None:
        if not 1 <= max_pages <= 3:
            raise ValueError("max_pages must be between 1 and 3")
        self.base_url = base_url.rstrip("/")
        self.output_path = Path(output_path)
        self.max_pages = max_pages
        self.token = "expired-token"
        self.logs: list[dict[str, Any]] = []
        self.seen_ids: set[str] = set()
        self.seen_cursors: set[str] = set()

    def _log(self, event: str, **fields: Any) -> None:
        self.logs.append({"event": event, **fields})

    def _request_json(self, path: str, cursor: str | None = None) -> dict[str, Any]:
        query = ""
        if cursor is not None:
            query = "?" + urlencode({"cursor": cursor})
        request = Request(
            f"{self.base_url}{path}{query}",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _refresh(self) -> None:
        request = Request(f"{self.base_url}/refresh", method="POST")
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.token = payload["access_token"]
        self._log("session_refreshed")

    def _fetch_profiles(self, cursor: str) -> dict[str, Any]:
        refreshes = 0
        rate_limit_retries = 0
        while True:
            try:
                return self._request_json("/profiles", cursor)
            except HTTPError as exc:
                if exc.code == 401:
                    if refreshes >= 1:
                        self._log("request_failed", cursor=cursor, reason="401_after_refresh")
                        self._log("alert", reason="session_refresh_failed", cursor=cursor)
                        raise RuntimeError("session remained unauthorized after refresh") from exc
                    refreshes += 1
                    self._log("retry", cursor=cursor, reason="401_session_expired")
                    self._refresh()
                    continue
                if exc.code == 429:
                    if rate_limit_retries >= 3:
                        self._log("request_failed", cursor=cursor, reason="429_retry_exhausted")
                        self._log("alert", reason="rate_limit_retry_exhausted", cursor=cursor)
                        raise RuntimeError("rate limit retry budget exhausted") from exc
                    rate_limit_retries += 1
                    try:
                        retry_after = max(0.0, float(exc.headers.get("Retry-After", "0")))
                    except ValueError:
                        retry_after = 0.0
                    self._log("retry", cursor=cursor, reason="429_rate_limited", retry_after=retry_after)
                    if retry_after > 0:
                        time.sleep(retry_after)
                    continue
                raise

    @staticmethod
    def _validate_profile(profile: Any) -> tuple[bool, str | None]:
        if not isinstance(profile, dict):
            return False, "profile_not_object"
        for field_name in ("id", "name"):
            if not profile.get(field_name):
                return False, f"missing_{field_name}"
        return True, None

    @staticmethod
    def _cursor_key(cursor: str) -> str:
        return "<empty>" if cursor == "" else cursor

    def crawl(self) -> CrawlResult:
        self.logs = []
        self.seen_ids = set()
        self.seen_cursors = set()
        cursor = ""
        page = 0
        profiles: list[dict[str, Any]] = []

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", encoding="utf-8") as output:
            while page < self.max_pages:
                cursor_key = self._cursor_key(cursor)
                if cursor_key in self.seen_cursors:
                    self._log("stop", reason="cursor_loop", cursor=cursor, page=page + 1)
                    self._log("alert", reason="cursor_loop", cursor=cursor)
                    return CrawlResult(profiles, self.logs, "cursor_loop")
                if cursor == "":
                    self._log("empty_cursor_start")
                self.seen_cursors.add(cursor_key)

                page += 1
                self._log("page_fetch", page=page, cursor=cursor)
                payload = self._fetch_profiles(cursor)
                if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list) or "next_cursor" not in payload or not isinstance(payload["next_cursor"], str):
                    self._log("stop", reason="schema_error", cursor=cursor, page=page)
                    self._log("alert", reason="schema_error", cursor=cursor)
                    return CrawlResult(profiles, self.logs, "schema_error")

                for profile in payload["profiles"]:
                    valid, error = self._validate_profile(profile)
                    if not valid:
                        self._log("validation_error", page=page, cursor=cursor, error=error, profile=profile)
                        continue
                    profile_id = profile["id"]
                    if profile_id in self.seen_ids:
                        self._log("duplicate_profile", page=page, cursor=cursor, profile_id=profile_id)
                        continue
                    self.seen_ids.add(profile_id)
                    profiles.append(profile)
                    output.write(json.dumps(profile, sort_keys=True) + "\n")

                next_cursor = payload["next_cursor"]
                self._log("page_done", page=page, cursor=cursor, next_cursor=next_cursor)
                if not next_cursor:
                    self._log("stop", reason="end_of_results", cursor=next_cursor, page=page)
                    return CrawlResult(profiles, self.logs, "end_of_results")
                if self._cursor_key(next_cursor) in self.seen_cursors:
                    self._log("stop", reason="cursor_loop", cursor=next_cursor, page=page)
                    self._log("alert", reason="cursor_loop", cursor=next_cursor)
                    return CrawlResult(profiles, self.logs, "cursor_loop")
                cursor = next_cursor

        self._log("stop", reason="max_pages", cursor=cursor, page=page)
        return CrawlResult(profiles, self.logs, "max_pages")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python -m q2_crawler.src.crawler <base_url> <output_jsonl>", file=sys.stderr)
        return 2
    crawler = ProfileCrawler(argv[1], argv[2])
    try:
        result = crawler.crawl()
    except Exception as exc:
        for log in crawler.logs:
            print(json.dumps(log, sort_keys=True), file=sys.stderr)
        print(json.dumps({"event": "error", "message": str(exc)}), file=sys.stderr)
        return 1
    for log in result.logs:
        print(json.dumps(log, sort_keys=True), file=sys.stderr)
    print(json.dumps({"profiles": len(result.profiles), "stop_reason": result.stop_reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
