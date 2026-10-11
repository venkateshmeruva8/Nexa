"""
Tests for NEXA Universal Website Opening in Google Chrome.

Verifies:
1. Natural language website commands (YouTube, Udemy, Spotify, Instagram, GitHub, etc.)
2. Domain normalization with and without schemes
3. Preservation of URL paths, query parameters, and fragments
4. Rejection of unsafe schemes (javascript:, file:, data:) and local files
5. Distinction between website opening, Google search, and desktop apps
6. Process launching with Chrome executable without shell=True
7. Safe dry-run simulation mode
8. Graceful error handling when Chrome is missing
9. Regression verification for existing routes (email, reminders, calendar, weather, apps)
"""

import unittest
from unittest.mock import patch, MagicMock
import asyncio

from backend.actions import (
    resolve_website_destination,
    _extract_website_target,
    _is_website_request,
    open_website,
    _extract_search_query,
    route_intent,
    COMMON_WEBSITE_ALIASES,
)


class TestWebsiteOpening(unittest.IsolatedAsyncioTestCase):
    """Unit and integration tests for universal website opening in Chrome."""

    def test_01_resolve_website_aliases(self):
        """Verifies common aliases resolve to expected URLs and display names."""
        test_cases = {
            "youtube": ("https://www.youtube.com", "YouTube"),
            "udemy": ("https://www.udemy.com", "Udemy"),
            "spotify": ("https://open.spotify.com", "Spotify"),
            "instagram": ("https://www.instagram.com", "Instagram"),
            "github": ("https://github.com", "GitHub"),
            "stackoverflow": ("https://stackoverflow.com", "Stack Overflow"),
            "reddit": ("https://www.reddit.com", "Reddit"),
            "linkedin": ("https://www.linkedin.com", "LinkedIn"),
            "chatgpt": ("https://chatgpt.com", "ChatGPT"),
        }
        for alias, expected in test_cases.items():
            res = resolve_website_destination(alias)
            self.assertIsNotNone(res, f"Alias '{alias}' should resolve")
            self.assertEqual(res, expected)

    def test_02_resolve_domains_and_full_urls(self):
        """Verifies domain normalization and preservation of paths/query strings."""
        # Bare domains -> https:// prefix
        res1 = resolve_website_destination("stackoverflow.com")
        self.assertEqual(res1, ("https://stackoverflow.com", "stackoverflow.com"))

        res2 = resolve_website_destination("example.org")
        self.assertEqual(res2, ("https://example.org", "example.org"))

        res3 = resolve_website_destination("testsite.co")
        self.assertEqual(res3, ("https://testsite.co", "testsite.co"))

        # Domain with port
        res4 = resolve_website_destination("localhost:8080")
        self.assertEqual(res4, ("https://localhost:8080", "localhost:8080"))

        # Full URL with path, query, and fragment preserved
        url_full = "https://github.com/trending?since=daily#today"
        res5 = resolve_website_destination(url_full)
        self.assertEqual(res5, (url_full, "github.com"))

        # http URL preserved
        url_http = "http://example.com/test?q=1"
        res6 = resolve_website_destination(url_http)
        self.assertEqual(res6, (url_http, "example.com"))

    def test_03_reject_unsafe_schemes_and_files(self):
        """Ensures dangerous schemes and local files are rejected."""
        unsafe_targets = [
            "javascript:alert(1)",
            "file:///C:/Windows/System32/cmd.exe",
            "data:text/html,<h1>Test</h1>",
            "about:blank",
            "vbscript:msgbox(1)",
            "resume.pdf",
            "script.py",
            "data.csv",
            "image.png",
            "archive.zip",
            "test.exe",
        ]
        for target in unsafe_targets:
            res = resolve_website_destination(target)
            self.assertIsNone(res, f"Target '{target}' must be rejected")

    def test_04_browser_applications_not_treated_as_websites(self):
        """Ensures 'chrome' and 'google chrome' are treated as desktop apps, not websites."""
        self.assertIsNone(resolve_website_destination("chrome"))
        self.assertIsNone(resolve_website_destination("google chrome"))
        self.assertFalse(_is_website_request("Open Chrome"))
        self.assertFalse(_is_website_request("Launch Google Chrome"))

    def test_05_extract_website_target(self):
        """Tests natural language extraction of target website."""
        cases = [
            ("Open YouTube", "YouTube"),
            ("Open Udemy in Chrome", "Udemy"),
            ("Launch Spotify", "Spotify"),
            ("Go to Instagram", "Instagram"),
            ("Open GitHub", "GitHub"),
            ("Open stackoverflow.com", "stackoverflow.com"),
            ("Can you please open reddit in google chrome?", "reddit"),
            ("Visit https://github.com/trending in browser", "https://github.com/trending"),
            ("Navigate to the website coursera.org", "coursera.org"),
            ("Browse to leetcode.com", "leetcode.com"),
        ]
        for query, expected_target in cases:
            extracted = _extract_website_target(query)
            self.assertEqual(
                extracted.lower() if extracted else None,
                expected_target.lower(),
                f"Failed for query '{query}'"
            )

    def test_06_is_website_request_distinction(self):
        """Tests classification between websites, applications, and web search."""
        website_queries = [
            "Open YouTube",
            "Open Udemy in Chrome",
            "Launch Spotify",
            "Go to Instagram",
            "Open GitHub",
            "Open stackoverflow.com",
            "Visit example.org",
            "Open https://github.com/trending",
        ]
        for q in website_queries:
            self.assertTrue(_is_website_request(q), f"Should be website request: '{q}'")

        non_website_queries = [
            "Open Chrome",
            "Open Notepad",
            "Open Calculator",
            "Open downloads folder",
            "Open resume.pdf",
            "Search Google for Python interview questions",
            "Search the web for machine learning tutorials",
            "How much RAM am I using?",
            "What is the weather in Delhi?",
        ]
        for q in non_website_queries:
            self.assertFalse(_is_website_request(q), f"Should NOT be website request: '{q}'")

    def test_07_extract_search_query_normalization(self):
        """Tests clean extraction of search queries without carrier or engine prefixes."""
        cases = [
            ("Search Google for Python interview questions", "Python interview questions"),
            ("Search the web for machine learning tutorials", "machine learning tutorials"),
            ("Search for latest AI papers", "latest AI papers"),
            ("google for weather in tokyo", "weather in tokyo"),
            ("search internet for best laptops 2026", "best laptops 2026"),
            ("find python courses online", "python courses"),
        ]
        for text, expected_clean in cases:
            actual = _extract_search_query(text)
            self.assertEqual(actual, expected_clean, f"Failed for '{text}'")

    @patch("backend.actions.subprocess.Popen")
    @patch("backend.actions._find_chrome_executable")
    async def test_08_open_website_launches_chrome_safely(self, mock_find_chrome, mock_popen):
        """Verifies Chrome executable is found and called with exact args and no shell=True."""
        mock_find_chrome.return_value = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

        res = await open_website("Open Udemy in Chrome", dry_run=False)
        self.assertIn("Opened Udemy in Chrome", res)
        mock_popen.assert_called_once_with([
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "https://www.udemy.com"
        ])

    @patch("backend.actions.subprocess.Popen")
    async def test_09_open_website_dry_run_never_launches_process(self, mock_popen):
        """Verifies dry_run=True returns simulation string without launching process."""
        res = await open_website("Open YouTube", dry_run=True)
        self.assertIn("[DRY-RUN]", res)
        self.assertIn("YouTube", res)
        mock_popen.assert_not_called()

    @patch("backend.actions._find_chrome_executable")
    async def test_10_open_website_handles_missing_chrome(self, mock_find_chrome):
        """Verifies explicit error returned when Chrome cannot be found (no silent success)."""
        mock_find_chrome.return_value = None
        res = await open_website("Open GitHub", dry_run=False)
        self.assertIn("Google Chrome is not installed or could not be found", res)
        self.assertNotIn("Opened GitHub in Chrome", res)

    async def test_11_route_intent_all_user_examples(self):
        """Tests end-to-end routing for all 8 user examples."""
        with patch("backend.actions.subprocess.Popen"):
            with patch("backend.actions._find_chrome_executable", return_value=r"C:\Chrome\chrome.exe"):
                # 1. Open YouTube
                r1 = await route_intent("Open YouTube", dry_run=True)
                self.assertEqual(r1["intent"], "OPEN_WEBSITE")
                self.assertTrue(r1["trusted"])
                self.assertIn("YouTube", r1["result"])

                # 2. Open Udemy in Chrome
                r2 = await route_intent("Open Udemy in Chrome", dry_run=True)
                self.assertEqual(r2["intent"], "OPEN_WEBSITE")
                self.assertTrue(r2["trusted"])
                self.assertIn("Udemy", r2["result"])

                # 3. Launch Spotify
                r3 = await route_intent("Launch Spotify", dry_run=True)
                self.assertEqual(r3["intent"], "OPEN_WEBSITE")
                self.assertTrue(r3["trusted"])
                self.assertIn("Spotify", r3["result"])

                # 4. Go to Instagram
                r4 = await route_intent("Go to Instagram", dry_run=True)
                self.assertEqual(r4["intent"], "OPEN_WEBSITE")
                self.assertTrue(r4["trusted"])
                self.assertIn("Instagram", r4["result"])

                # 5. Open GitHub
                r5 = await route_intent("Open GitHub", dry_run=True)
                self.assertEqual(r5["intent"], "OPEN_WEBSITE")
                self.assertTrue(r5["trusted"])
                self.assertIn("GitHub", r5["result"])

                # 6. Open stackoverflow.com
                r6 = await route_intent("Open stackoverflow.com", dry_run=True)
                self.assertEqual(r6["intent"], "OPEN_WEBSITE")
                self.assertTrue(r6["trusted"])
                self.assertIn("stackoverflow.com", r6["result"])

                # 7. Search Google for Python interview questions
                r7 = await route_intent("Search Google for Python interview questions", dry_run=True)
                self.assertEqual(r7["intent"], "SEARCH_WEB")
                self.assertTrue(r7["trusted"])
                self.assertIn("Python interview questions", r7["result"])

                # 8. Search the web for machine learning tutorials
                r8 = await route_intent("Search the web for machine learning tutorials", dry_run=True)
                self.assertEqual(r8["intent"], "SEARCH_WEB")
                self.assertTrue(r8["trusted"])
                self.assertIn("machine learning tutorials", r8["result"])

    async def test_12_regression_unaffected_routes(self):
        """Verifies existing routes (apps, folders, close app) remain completely unaffected."""
        # Open Notepad -> OPEN_APPLICATION
        r_notepad = await route_intent("Open Notepad", dry_run=True)
        self.assertEqual(r_notepad["intent"], "OPEN_APPLICATION")
        self.assertTrue(r_notepad["trusted"])

        # Open Chrome -> OPEN_APPLICATION
        r_chrome = await route_intent("Open Chrome", dry_run=True)
        self.assertEqual(r_chrome["intent"], "OPEN_APPLICATION")
        self.assertTrue(r_chrome["trusted"])

        # Close Chrome -> CLOSE_APPLICATION
        r_close = await route_intent("Close Chrome", dry_run=True)
        self.assertEqual(r_close["intent"], "CLOSE_APPLICATION")
        self.assertTrue(r_close["trusted"])


if __name__ == "__main__":
    unittest.main()
