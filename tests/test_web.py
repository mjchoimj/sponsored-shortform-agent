"""T23 웹 검색 켜고 끄기 · 캐시 테스트 — 실제 Tavily 를 부르지 않는다.

실행: python -m unittest tests.test_web -v
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, web


class ToggleTest(unittest.TestCase):
    def test_option_wins(self):
        with patch.object(config, "WEB_SEARCH", "off"):
            self.assertTrue(web.web_enabled(True))
        with patch.object(config, "WEB_SEARCH", "on"):
            self.assertFalse(web.web_enabled(False))

    def test_env_setting(self):
        with patch.object(config, "WEB_SEARCH", "on"), patch.object(config, "TAVILY_API_KEY", ""):
            self.assertTrue(web.web_enabled())
        with patch.object(config, "WEB_SEARCH", "off"), patch.object(config, "TAVILY_API_KEY", "k"):
            self.assertFalse(web.web_enabled())

    def test_auto_follows_key(self):
        with patch.object(config, "WEB_SEARCH", "auto"):
            with patch.object(config, "TAVILY_API_KEY", "k"):
                self.assertTrue(web.web_enabled())
            with patch.object(config, "TAVILY_API_KEY", ""):
                self.assertFalse(web.web_enabled())


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = patch.object(web, "CACHE_DIR", Path(self.tmp.name))
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def test_no_key_no_cache_skips(self):
        with patch.object(config, "TAVILY_API_KEY", ""):
            self.assertIn("웹 검색 불가", web.web_search("없는 검색어"))

    def test_cache_used_without_key(self):
        q = "포근 보풀 제거기 사양"
        web._cache_path(q).write_text(json.dumps(
            {"query": q, "results": [{"title": "T", "url": "u", "content": "무게 180g"}]}, ensure_ascii=False),
            encoding="utf-8")
        with patch.object(config, "TAVILY_API_KEY", ""):
            self.assertIn("무게 180g", web.web_search(q))

    def test_search_saves_cache_and_reuses(self):
        calls = []

        def fake(q):
            calls.append(q)
            return [{"title": "T", "url": "u", "content": "결과"}]

        with patch.object(config, "TAVILY_API_KEY", "k"), patch.object(web, "_tavily", fake):
            web.web_search("검색어")
            web.web_search("검색어")
        self.assertEqual(len(calls), 1)  # 두 번째는 캐시
        self.assertTrue(web._cache_path("검색어").exists())


if __name__ == "__main__":
    unittest.main()
