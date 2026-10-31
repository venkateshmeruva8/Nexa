"""
Tests for NEXA UI Navigation, 4-Screen Switching, and Context-Aware Floating Action Cards.
"""
import os
import sys
import unittest
import time
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

# Ensure QGuiApplication is initialized with offscreen platform for testing
os.environ["QT_QPA_PLATFORM"] = "offscreen"
app = QGuiApplication.instance()
if app is None:
    app = QGuiApplication(sys.argv)

from frontend.controller import NexaUIController


class TestUICardsAndNavigation(unittest.TestCase):

    def setUp(self):
        self.controller = NexaUIController()

    def tearDown(self):
        if hasattr(self, "controller"):
            self.controller.shutdown()

    def test_01_navigation_state_switching_all_four_screens(self):
        """Verify navigation transitions cleanly between Home(0), Chat(1), Apps(2), and Settings(3)."""
        nav_signals = []
        self.controller.navChanged.connect(lambda: nav_signals.append(self.controller.activeNav))

        self.assertEqual(self.controller.activeNav, 0)

        # 0 -> 1 (Chat)
        self.controller.selectNav(1)
        self.assertEqual(self.controller.activeNav, 1)

        # 1 -> 2 (Apps)
        self.controller.selectNav(2)
        self.assertEqual(self.controller.activeNav, 2)

        # 2 -> 3 (Settings)
        self.controller.selectNav(3)
        self.assertEqual(self.controller.activeNav, 3)

        # 3 -> 0 (Home)
        self.controller.selectNav(0)
        self.assertEqual(self.controller.activeNav, 0)

        # Verify same index is a no-op
        self.controller.selectNav(0)
        self.assertEqual(len(nav_signals), 4)

    def test_02_floating_action_card_creation_and_categories(self):
        """Verify cards can be created across all 6 supported categories with correct schema."""
        categories = ["FILE", "SEARCH", "APP", "REMINDER", "EMAIL", "SYSTEM"]

        for cat in categories:
            cid = self.controller.triggerActionCard(
                card_type=cat,
                title=f"Test {cat}",
                subtitle=f"Subtitle {cat}",
                status="loading",
                details=f"Details for {cat}",
                icon=cat,
            )
            self.assertTrue(cid.startswith("card_"))

        cards = self.controller.actionCards
        self.assertEqual(len(cards), 4)  # Capped at 4 max visible cards

        top_card = cards[0]
        self.assertEqual(top_card["type"], "SYSTEM")
        self.assertEqual(top_card["status"], "loading")

    def test_03_floating_action_card_dismissal(self):
        """Verify manual card dismissal removes card and emits signal."""
        cid1 = self.controller.triggerActionCard("APP", "App 1", status="loading")
        cid2 = self.controller.triggerActionCard("APP", "App 2", status="loading")

        self.assertEqual(len(self.controller.actionCards), 2)

        # Dismiss card 1
        self.controller.dismissCard(cid1)
        remaining_ids = [c["id"] for c in self.controller.actionCards]
        self.assertNotIn(cid1, remaining_ids)
        self.assertIn(cid2, remaining_ids)
        self.assertEqual(len(self.controller.actionCards), 1)

    def test_04_transcript_parser_app_launch_result(self):
        """Verify verified assistant confirmation 'Opened Calculator.' generates APP card."""
        self.controller._action_cards.clear()
        self.controller._on_transcript_received(
            role="assistant",
            text="Opened Calculator.",
            is_final=True,
            segment_id="seg_app_01",
        )

        cards = self.controller.actionCards
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["type"], "APP")
        self.assertEqual(cards[0]["title"], "Application Running")
        self.assertEqual(cards[0]["subtitle"], "Calculator")
        self.assertEqual(cards[0]["status"], "success")

    def test_05_transcript_parser_web_search_result(self):
        """Verify verified assistant confirmation 'Searching for python in Chrome.' generates SEARCH card."""
        self.controller._action_cards.clear()
        self.controller._on_transcript_received(
            role="assistant",
            text="Searching for artificial intelligence in Chrome.",
            is_final=True,
            segment_id="seg_search_01",
        )

        cards = self.controller.actionCards
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["type"], "SEARCH")
        self.assertEqual(cards[0]["title"], "Web Search")
        self.assertIn("artificial intelligence", cards[0]["subtitle"])
        self.assertEqual(cards[0]["status"], "success")

    def test_06_transcript_parser_file_operations_result(self):
        """Verify file/folder confirmations generate FILE card."""
        self.controller._action_cards.clear()
        self.controller._on_transcript_received(
            role="assistant",
            text="Opened downloads folder.",
            is_final=True,
            segment_id="seg_file_01",
        )

        cards = self.controller.actionCards
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["type"], "FILE")
        self.assertEqual(cards[0]["title"], "Folder Opened")
        self.assertEqual(cards[0]["subtitle"], "downloads")

    def test_07_transcript_parser_reminder_result(self):
        """Verify reminder confirmation generates REMINDER card."""
        self.controller._action_cards.clear()
        self.controller._on_transcript_received(
            role="assistant",
            text="Reminder set: 'Call Doctor' in 15 minutes (08:00 PM IST).",
            is_final=True,
            segment_id="seg_rem_01",
        )

        cards = self.controller.actionCards
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["type"], "REMINDER")
        self.assertEqual(cards[0]["title"], "Reminder Scheduled")
        self.assertIn("Call Doctor", cards[0]["subtitle"])
        self.assertEqual(cards[0]["status"], "success")

    def test_08_transcript_parser_email_workflow_status(self):
        """Verify email staging and approval confirmations generate EMAIL card with accurate statuses."""
        self.controller._action_cards.clear()

        # Staged
        self.controller._on_transcript_received(
            role="assistant",
            text="Email Draft Prepared & Staged: To: team@nexa.com Subject: Review",
            is_final=True,
            segment_id="seg_email_01",
        )
        cards = self.controller.actionCards
        self.assertEqual(cards[0]["type"], "EMAIL")
        self.assertEqual(cards[0]["status"], "staged")

        # Dispatched
        self.controller._on_transcript_received(
            role="assistant",
            text="Your email has been sent successfully.",
            is_final=True,
            segment_id="seg_email_02",
        )
        self.assertEqual(self.controller.actionCards[0]["type"], "EMAIL")
        self.assertEqual(self.controller.actionCards[0]["status"], "success")

    def test_09_transcript_parser_system_volume_result(self):
        """Verify volume adjustments generate SYSTEM card."""
        self.controller._action_cards.clear()
        self.controller._on_transcript_received(
            role="assistant",
            text="Volume adjusted to 75%.",
            is_final=True,
            segment_id="seg_sys_01",
        )

        cards = self.controller.actionCards
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["type"], "SYSTEM")
        self.assertEqual(cards[0]["title"], "Volume Adjusted")
        self.assertEqual(cards[0]["subtitle"], "Level: 75%")

    def test_10_interactive_slots_send_message_and_clear(self):
        """Verify sendMessage appends user and assistant reply, and clearMessages resets."""
        initial_count = len(self.controller.messages)
        self.controller.sendMessage("What is the time?")
        self.assertEqual(len(self.controller.messages), initial_count + 2)

        self.controller.clearMessages()
        self.assertEqual(len(self.controller.messages), 0)

    def test_11_qml_engine_loads_all_views_without_errors(self):
        """Verify QQmlApplicationEngine cleanly parses Main.qml and all associated components."""
        base_dir = Path(__file__).resolve().parent.parent / "frontend"
        qml_main = base_dir / "qml" / "Main.qml"

        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("controller", self.controller)
        engine.rootContext().setContextProperty("nexaController", self.controller)

        engine.load(QUrl.fromLocalFile(str(qml_main)))
        root_objs = engine.rootObjects()
        self.assertTrue(len(root_objs) > 0, "Main.qml root object must load successfully")


if __name__ == "__main__":
    unittest.main()
