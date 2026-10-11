import os
import sys
import re
import time
import logging
import asyncio
import unittest
from unittest.mock import patch, MagicMock

REPO_ROOT = r"c:\Users\Hp\Desktop\Nexa"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ["GMAIL_USER"] = "testuser@gmail.com"
os.environ["GMAIL_APP_PASSWORD"] = "abcd efgh ijkl mnop"

from backend.tools import (
    send_email,
    dispatch_staged_email,
    has_pending_email_for_session,
    get_pending_email_for_session,
    clear_pending_email_for_session,
    clear_pending_email_confirmation,
    has_pending_recipient_verification_for_session,
    get_pending_recipient_verification_for_session,
    clear_pending_recipient_verification_for_session,
    clear_all_pending_recipient_verifications,
    set_enforce_recipient_verification_for_session,
    _PENDING_EMAIL_SESSIONS,
    _PENDING_RECIPIENT_VERIFICATIONS,
    _RECENT_EMAIL_DISPATCHES,
)
from backend.actions import (
    handle_local_email_approval,
    handle_local_recipient_verification,
)


class MockLiveKitRunContext:
    """Simulates a live LiveKit Agent RunContext with session and room attributes."""
    def __init__(self, room_name: str = "test_live_room"):
        self.room = MagicMock()
        self.room.name = room_name
        self.session = MagicMock()
        self.session.id = room_name
        self.session.room_io = None
        self.agent = MagicMock()
        self.agent.session_id = room_name


class TestEmailRecipientVerification(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        clear_pending_email_confirmation()
        clear_all_pending_recipient_verifications()
        _RECENT_EMAIL_DISPATCHES.clear()

    def tearDown(self):
        clear_pending_email_confirmation()
        clear_all_pending_recipient_verifications()
        _RECENT_EMAIL_DISPATCHES.clear()

    async def test_01_send_email_in_live_context_requires_recipient_verification_before_staging(self):
        """Live agent context requires recipient verification and refuses to stage the draft prematurely."""
        ctx = MockLiveKitRunContext("session_live_01")
        res = await send_email(
            context=ctx,
            to_email="recipient@example.com",
            subject="Status Report",
            message="All systems operational.",
        )

        # Must return Recipient Verification prompt, NOT draft staging notice
        self.assertIn("Recipient Verification Required (Email NOT drafted yet):", res)
        self.assertIn("• Candidate Recipient: recipient@example.com", res)
        self.assertNotIn("Email Draft Prepared & Staged", res)

        # Must NOT be staged into _PENDING_EMAIL_SESSIONS yet
        self.assertFalse(has_pending_email_for_session("session_live_01"))

        # Must be in _PENDING_RECIPIENT_VERIFICATIONS
        self.assertTrue(has_pending_recipient_verification_for_session("session_live_01"))
        pending = get_pending_recipient_verification_for_session("session_live_01")
        self.assertIsNotNone(pending)
        self.assertEqual(pending["candidate_to"], "recipient@example.com")
        self.assertFalse(pending["verified"])

    async def test_02_recipient_verification_prompt_reads_back_exact_address_verbatim(self):
        """Verification prompt preserves exact alphanumeric address with zero heuristic alterations."""
        ctx = MockLiveKitRunContext("session_live_02")
        complex_address = "venakateshvenky93980@gmail.com"
        res = await send_email(
            context=ctx,
            to_email=complex_address,
            subject="Test Subject",
            message="Test Message",
        )

        self.assertIn(f"• Candidate Recipient: {complex_address}", res)
        self.assertIn(f"'{complex_address}'", res)
        # Verify no digits dropped or letters altered
        self.assertIn("93980", res)
        self.assertIn("venky", res)

    async def test_03_explicit_yes_verifies_recipient_and_stages_draft(self):
        """User saying YES to candidate verification marks recipient verified and stages draft."""
        session_id = "session_live_03"
        ctx = MockLiveKitRunContext(session_id)
        await send_email(
            context=ctx,
            to_email="verified_user@example.com",
            subject="Project Plan",
            message="Here is the project outline.",
        )
        self.assertFalse(has_pending_email_for_session(session_id))
        self.assertTrue(has_pending_recipient_verification_for_session(session_id))

        # User speaks "Yes, that is correct"
        ver_res = await handle_local_recipient_verification(
            text="Yes, that is correct.",
            session_id=session_id,
            user_authorized=True,
        )

        self.assertIsNotNone(ver_res)
        self.assertTrue(ver_res["handled"])
        self.assertEqual(ver_res["intent"], "CONFIRM_RECIPIENT")
        self.assertEqual(ver_res["status"], "VERIFIED")
        self.assertIn("Recipient confirmed as verified_user@example.com", ver_res["spoken_response"])
        self.assertIn("Would you like me to send this email? Please answer YES to send or NO to cancel.", ver_res["spoken_response"])

        # Candidate verification is now consumed/cleared
        self.assertFalse(has_pending_recipient_verification_for_session(session_id))

        # Email draft is NOW staged for final approval (Phase 2)
        self.assertTrue(has_pending_email_for_session(session_id))
        staged = get_pending_email_for_session(session_id)
        self.assertEqual(staged["to_email"], "verified_user@example.com")
        self.assertEqual(staged["subject"], "Project Plan")

    async def test_04_recipient_confirmation_never_calls_smtp(self):
        """Recipient confirmation must NEVER authorize or trigger SMTP dispatch."""
        session_id = "session_live_04"
        ctx = MockLiveKitRunContext(session_id)
        await send_email(
            context=ctx,
            to_email="safety_check@example.com",
            subject="Safety Test",
            message="Check zero SMTP calls.",
        )

        mock_smtp_inst = MagicMock()
        with patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_inst)):
            # Confirm recipient
            ver_res = await handle_local_recipient_verification(
                text="Yes",
                session_id=session_id,
                user_authorized=True,
            )
            self.assertEqual(ver_res["status"], "VERIFIED")

            # SMTP sendmail must be called ZERO times upon recipient verification!
            mock_smtp_inst.sendmail.assert_not_called()

    async def test_05_subsequent_send_approval_dispatches_via_smtp(self):
        """Complete 2-phase sequence: Recipient confirmation stages draft -> second YES dispatches via SMTP."""
        session_id = "session_live_05"
        ctx = MockLiveKitRunContext(session_id)

        # 1. Gemini calls send_email -> Recipient Verification required
        init_res = await send_email(
            context=ctx,
            to_email="target@example.com",
            subject="Two Phase Flow",
            message="Testing two distinct approval phases.",
        )
        self.assertIn("Recipient Verification Required", init_res)

        # 2. Phase 1: User confirms recipient
        mock_smtp_inst = MagicMock()
        with patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_inst)):
            recip_res = await handle_local_recipient_verification(
                text="Yes, that's correct",
                session_id=session_id,
                user_authorized=True,
            )
            self.assertEqual(recip_res["status"], "VERIFIED")
            mock_smtp_inst.sendmail.assert_not_called()

            # 3. Phase 2: User approves sending the staged draft
            send_res = await handle_local_email_approval(
                text="Yes, go ahead and send it",
                session_id=session_id,
                user_authorized=True,
            )
            self.assertIsNotNone(send_res)
            self.assertEqual(send_res["status"], "SUCCESS")
            self.assertEqual(send_res["spoken_response"], "Your email has been sent successfully.")

            # SMTP sendmail called exactly once with verified recipient
            mock_smtp_inst.sendmail.assert_called_once()
            from_arg, recips_arg, body_arg = mock_smtp_inst.sendmail.call_args[0]
            self.assertEqual(recips_arg, ["target@example.com"])
            self.assertIn("Subject: Two Phase Flow", body_arg)

            # Both stages now consumed
            self.assertFalse(has_pending_email_for_session(session_id))
            self.assertFalse(has_pending_recipient_verification_for_session(session_id))

    async def test_06_address_correction_updates_candidate_and_requires_reconfirmation(self):
        """User providing a corrected address updates candidate and keeps verification pending."""
        session_id = "session_live_06"
        ctx = MockLiveKitRunContext(session_id)

        # Initially staged misheard address
        await send_email(
            context=ctx,
            to_email="tvenkateshtvenkatesn@gmail.com",
            subject="Important Notes",
            message="Meeting notes attached.",
        )

        # User provides correction: "No, it's venakateshvenky93980@gmail.com"
        correct_res = await handle_local_recipient_verification(
            text="No, the correct address is venakateshvenky93980@gmail.com",
            session_id=session_id,
            user_authorized=True,
        )

        self.assertIsNotNone(correct_res)
        self.assertEqual(correct_res["status"], "CORRECTED")
        self.assertEqual(correct_res["candidate_recipient"], "venakateshvenky93980@gmail.com")
        self.assertIn("venakateshvenky93980@gmail.com", correct_res["spoken_response"])

        # Still NOT staged in _PENDING_EMAIL_SESSIONS
        self.assertFalse(has_pending_email_for_session(session_id))

        # Candidate in _PENDING_RECIPIENT_VERIFICATIONS is updated to corrected address
        pending = get_pending_recipient_verification_for_session(session_id)
        self.assertEqual(pending["candidate_to"], "venakateshvenky93980@gmail.com")
        self.assertFalse(pending["verified"])

        # Now user confirms the corrected address
        confirm_res = await handle_local_recipient_verification(
            text="Yes, that is correct",
            session_id=session_id,
            user_authorized=True,
        )
        self.assertEqual(confirm_res["status"], "VERIFIED")
        self.assertTrue(has_pending_email_for_session(session_id))
        staged = get_pending_email_for_session(session_id)
        self.assertEqual(staged["to_email"], "venakateshvenky93980@gmail.com")

    async def test_07_cancellation_clears_verification_and_never_stages(self):
        """Explicit cancellation discards the candidate draft without staging."""
        session_id = "session_live_07"
        ctx = MockLiveKitRunContext(session_id)
        await send_email(
            context=ctx,
            to_email="cancel_candidate@example.com",
            subject="Never Mind",
            message="Do not send.",
        )

        cancel_res = await handle_local_recipient_verification(
            text="Cancel email draft",
            session_id=session_id,
            user_authorized=True,
        )
        self.assertIsNotNone(cancel_res)
        self.assertEqual(cancel_res["status"], "CANCELLED")
        self.assertIn("cancelled", cancel_res["spoken_response"].lower())

        # Verification cleared, email never staged
        self.assertFalse(has_pending_recipient_verification_for_session(session_id))
        self.assertFalse(has_pending_email_for_session(session_id))

    async def test_08_ambiguous_utterances_reject_verification(self):
        """Ambiguous phrases ('maybe', 'send it now') fail closed and re-prompt candidate address."""
        session_id = "session_live_08"
        ctx = MockLiveKitRunContext(session_id)
        await send_email(
            context=ctx,
            to_email="ambig@example.com",
            subject="Ambiguous Test",
            message="Testing hesitation.",
        )

        # Premature send command before verifying recipient must fail closed
        res1 = await handle_local_recipient_verification(
            text="Send it now",
            session_id=session_id,
            user_authorized=True,
        )
        self.assertEqual(res1["status"], "AMBIGUOUS")
        self.assertIn("ambig@example.com", res1["spoken_response"])
        self.assertFalse(has_pending_email_for_session(session_id))

        # Hesitation / modification
        res2 = await handle_local_recipient_verification(
            text="Yes, but wait a minute",
            session_id=session_id,
            user_authorized=True,
        )
        self.assertEqual(res2["status"], "AMBIGUOUS")
        self.assertFalse(has_pending_email_for_session(session_id))

    async def test_09_attempts_to_bypass_verification_fail_closed(self):
        """Caller/LLM cannot bypass recipient verification in live context even by passing require_recipient_verification=False."""
        ctx = MockLiveKitRunContext("session_live_bypass")

        # Passing require_recipient_verification=False on live context MUST be ignored!
        res = await send_email(
            context=ctx,
            to_email="bypass_target@example.com",
            subject="Bypass Attempt",
            message="Should fail closed.",
            require_recipient_verification=False,
        )
        self.assertIn("Recipient Verification Required", res)
        self.assertFalse(has_pending_email_for_session("session_live_bypass"))

        # Calling dispatch_staged_email directly without verification fails closed
        dispatch_res = await dispatch_staged_email(
            session_id="session_live_bypass",
            confirmation_token="bogus_token",
            user_authorized=True,
        )
        self.assertIn("No pending email was found", dispatch_res)

    async def test_10_cross_session_isolation(self):
        """Candidate verification in session A cannot be confirmed or affected from session B."""
        ctx_a = MockLiveKitRunContext("session_iso_A")
        await send_email(
            context=ctx_a,
            to_email="alice@example.com",
            subject="Session A Subject",
            message="Body A",
        )
        self.assertTrue(has_pending_recipient_verification_for_session("session_iso_A"))
        self.assertFalse(has_pending_recipient_verification_for_session("session_iso_B"))

        # Attempt to confirm from session B returns None (no pending verification)
        res_b = await handle_local_recipient_verification(
            text="Yes, correct",
            session_id="session_iso_B",
            user_authorized=True,
        )
        self.assertIsNone(res_b)
        self.assertFalse(has_pending_email_for_session("session_iso_B"))
        self.assertFalse(has_pending_email_for_session("session_iso_A"))

    async def test_11_expired_recipient_verification_fails_closed(self):
        """Candidate verification past 300s expiration is automatically cleared and rejected."""
        session_id = "session_live_exp"
        ctx = MockLiveKitRunContext(session_id)
        await send_email(
            context=ctx,
            to_email="expired@example.com",
            subject="Expiry Test",
            message="Testing timeout.",
        )

        pending = get_pending_recipient_verification_for_session(session_id)
        self.assertIsNotNone(pending)
        # Fast-forward created_at by 305 seconds (> 300s timeout)
        pending["created_at"] = time.time() - 305.0

        # Verification check detects expiration and returns False
        self.assertFalse(has_pending_recipient_verification_for_session(session_id))

        # Attempting confirmation returns None
        exp_res = await handle_local_recipient_verification(
            text="Yes, correct",
            session_id=session_id,
            user_authorized=True,
        )
        self.assertIsNone(exp_res)
        self.assertFalse(has_pending_email_for_session(session_id))

    async def test_12_structured_lifecycle_logs_contain_no_secrets(self):
        """Verify structured lifecycle log tags are emitted and contain no passwords or secrets."""
        session_id = "session_live_audit"
        ctx = MockLiveKitRunContext(session_id)
        log_records = []

        class TestLogHandler(logging.Handler):
            def emit(self, record):
                log_records.append(self.format(record))

        handler = TestLogHandler()
        handler.setLevel(logging.INFO)
        root_logger = logging.getLogger()
        orig_level = root_logger.level
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)

        try:
            # 1. Pending verification
            await send_email(
                context=ctx,
                to_email="audit_user@example.com",
                subject="Audit Subject",
                message="Secret body content",
            )
            # 2. Correction
            await handle_local_recipient_verification(
                text="No it is audit_corrected@example.com",
                session_id=session_id,
                user_authorized=True,
            )
            # 3. Confirmation
            await handle_local_recipient_verification(
                text="Yes correct",
                session_id=session_id,
                user_authorized=True,
            )

            all_log = "\n".join(log_records)
            self.assertIn("RECIPIENT_VERIFICATION_PENDING", all_log)
            self.assertIn("RECIPIENT_VERIFICATION_CORRECTED", all_log)
            self.assertIn("RECIPIENT_VERIFICATION_CONFIRMED", all_log)
            self.assertIn("EMAIL_DRAFT_PENDING", all_log)

            # Passwords and secrets not leaked
            self.assertNotIn("abcd efgh ijkl mnop", all_log)
        finally:
            root_logger.removeHandler(handler)
            root_logger.setLevel(orig_level)


if __name__ == "__main__":
    unittest.main()
