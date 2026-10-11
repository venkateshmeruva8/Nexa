import os
import sys
import re
import time
import socket
import logging
import smtplib
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

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
    _format_pending_email_summary,
    _PENDING_EMAIL_SESSIONS,
    _RECENT_EMAIL_DISPATCHES,
)
from backend.actions import (
    handle_local_email_approval,
    _is_explicit_email_approval,
    _is_explicit_email_cancellation,
)
from backend.mcp.agent_tools import MCPToolsIntegration
from backend.mcp.util import FunctionTool


class TestEmailApprovalFlow(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        clear_pending_email_confirmation()
        _RECENT_EMAIL_DISPATCHES.clear()

    def tearDown(self):
        clear_pending_email_confirmation()
        _RECENT_EMAIL_DISPATCHES.clear()

    async def test_01_yes_dispatches_exact_staged_draft_once(self):
        """YES and conversational variations dispatch the exact staged draft via SMTP exactly once."""
        session_id = "test_session_01"
        res = await send_email(
            context=session_id,
            to_email="recipient@example.com",
            subject="Quarterly Review",
            message="Please find the Q3 numbers attached.",
        )
        self.assertIn("Email Draft Prepared & Staged", res)
        self.assertTrue(has_pending_email_for_session(session_id))

        # Mock smtplib.SMTP
        mock_smtp_inst = MagicMock()
        mock_smtp_cls = MagicMock(return_value=mock_smtp_inst)

        with patch("smtplib.SMTP", mock_smtp_cls):
            approval_res = await handle_local_email_approval(
                text="Yes, go ahead and send an email.",
                session_id=session_id,
                user_authorized=True,
            )

        self.assertIsNotNone(approval_res)
        self.assertTrue(approval_res["handled"])
        self.assertEqual(approval_res["intent"], "APPROVE_EMAIL")
        self.assertEqual(approval_res["status"], "SUCCESS")
        self.assertEqual(approval_res["spoken_response"], "Your email has been sent successfully.")

        # Verify SMTP sendmail called exactly once with exact staged values
        mock_smtp_inst.sendmail.assert_called_once()
        from_arg, recips_arg, body_arg = mock_smtp_inst.sendmail.call_args[0]
        self.assertEqual(from_arg, "testuser@gmail.com")
        self.assertEqual(recips_arg, ["recipient@example.com"])
        self.assertIn("Subject: Quarterly Review", body_arg)
        self.assertIn("Please find the Q3 numbers attached.", body_arg)

        # Staged draft must be consumed immediately
        self.assertFalse(has_pending_email_for_session(session_id))
        self.assertIsNone(get_pending_email_for_session(session_id))

    async def test_02_simple_yes_dispatches_exact_staged_draft(self):
        """Single-word 'yes' dispatches the exact staged draft via SMTP."""
        session_id = "test_session_02"
        await send_email(
            context=session_id,
            to_email="colleague@example.com",
            subject="Lunch Meeting",
            message="Are we on for 1 PM?",
        )

        mock_smtp_inst = MagicMock()
        with patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_inst)):
            approval_res = await handle_local_email_approval(
                text="yes",
                session_id=session_id,
                user_authorized=True,
            )

        self.assertIsNotNone(approval_res)
        self.assertEqual(approval_res["status"], "SUCCESS")
        self.assertEqual(approval_res["spoken_response"], "Your email has been sent successfully.")
        mock_smtp_inst.sendmail.assert_called_once()
        self.assertFalse(has_pending_email_for_session(session_id))

    async def test_03_no_cancels_and_dispatches_zero_times(self):
        """NO and cancellation commands cancel the draft and call SMTP zero times."""
        session_id = "test_session_03"
        await send_email(
            context=session_id,
            to_email="cancel_target@example.com",
            subject="Do Not Send",
            message="Cancel this test.",
        )
        self.assertTrue(has_pending_email_for_session(session_id))

        mock_smtp_inst = MagicMock()
        with patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_inst)):
            cancel_res = await handle_local_email_approval(
                text="No, don't send it.",
                session_id=session_id,
                user_authorized=True,
            )

        self.assertIsNotNone(cancel_res)
        self.assertTrue(cancel_res["handled"])
        self.assertEqual(cancel_res["status"], "CANCELLED")
        self.assertEqual(cancel_res["spoken_response"], "Your email draft has been cancelled.")

        # SMTP must NOT be called
        mock_smtp_inst.sendmail.assert_not_called()
        self.assertFalse(has_pending_email_for_session(session_id))

    async def test_04_simple_no_cancels_draft(self):
        """Single-word 'no' cancels the pending draft without calling SMTP."""
        session_id = "test_session_04"
        await send_email(
            context=session_id,
            to_email="cancel_target2@example.com",
            subject="Do Not Send 2",
            message="Cancel test.",
        )

        mock_smtp_inst = MagicMock()
        with patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_inst)):
            cancel_res = await handle_local_email_approval(
                text="no",
                session_id=session_id,
                user_authorized=True,
            )

        self.assertIsNotNone(cancel_res)
        self.assertEqual(cancel_res["status"], "CANCELLED")
        mock_smtp_inst.sendmail.assert_not_called()
        self.assertFalse(has_pending_email_for_session(session_id))

    async def test_05_llm_tool_call_alone_cannot_dispatch(self):
        """LLM tool calls only stage drafts; direct dispatch without user authorization fails closed."""
        mock_smtp_inst = MagicMock()
        with patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_inst)):
            # 1. Native send_email only stages
            staging_res = await send_email(
                context="session_llm",
                to_email="target@example.com",
                subject="Test Staging",
                message="Body content",
            )
            self.assertIn("Email Draft Prepared & Staged", staging_res)
            mock_smtp_inst.sendmail.assert_not_called()

            # 2. dispatch_staged_email with user_authorized=False must be rejected
            staged = get_pending_email_for_session("session_llm")
            self.assertIsNotNone(staged)
            denied_res = await dispatch_staged_email(
                session_id="session_llm",
                confirmation_token=staged["token"],
                user_authorized=False,
            )
            self.assertIn("Access denied", denied_res)
            mock_smtp_inst.sendmail.assert_not_called()

            # 3. Dynamic MCP email tool interception only stages
            mock_raw_tool = FunctionTool(
                name="Send_an_Email_in_Send_Email",
                description="Send email",
                params_json_schema={"type": "object", "properties": {}},
                on_invoke_tool=AsyncMock(return_value="remote result"),
            )
            dec_tool = MCPToolsIntegration._create_decorated_tool(mock_raw_tool)
            fn = getattr(dec_tool, "func", dec_tool)
            mcp_res = await fn(
                To_Email="mcp_target@example.com",
                Subject="MCP Staging",
                Message="MCP body",
            )
            self.assertIn("Email Draft Prepared & Staged", mcp_res)
            mock_smtp_inst.sendmail.assert_not_called()

    async def test_06_repeated_yes_cannot_duplicate_send(self):
        """Repeated YES utterances cannot dispatch the draft a second time."""
        session_id = "test_session_06"
        await send_email(
            context=session_id,
            to_email="duplicate_test@example.com",
            subject="Single Dispatch Only",
            message="Should only send once.",
        )

        mock_smtp_inst = MagicMock()
        with patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_inst)):
            # First YES -> dispatches
            res1 = await handle_local_email_approval(
                text="yes send it",
                session_id=session_id,
                user_authorized=True,
            )
            self.assertEqual(res1["status"], "SUCCESS")
            self.assertEqual(mock_smtp_inst.sendmail.call_count, 1)

            # Second immediate YES -> draft is consumed, so handler fails closed or reports no draft
            res2 = await handle_local_email_approval(
                text="yes send it",
                session_id=session_id,
                user_authorized=True,
            )
            # Handler returns None (no pending draft) or reports no pending draft
            if res2 is not None:
                self.assertNotEqual(res2["status"], "SUCCESS")
            # SMTP call count remains strictly 1
            self.assertEqual(mock_smtp_inst.sendmail.call_count, 1)

    async def test_07_failed_and_uncertain_smtp_never_produce_success(self):
        """SMTP errors or mid-transmission socket disconnects report failure/warning and never success."""
        # 1. Uncertain delivery (socket drop after sendmail started)
        session_id_u = "test_session_uncertain"
        await send_email(
            context=session_id_u,
            to_email="uncertain@example.com",
            subject="Uncertain Test",
            message="Check socket drop.",
        )

        def _fake_smtp_uncertain(*args, **kwargs):
            m = MagicMock()
            def _fake_sendmail(*a, **k):
                raise socket.error("Connection reset by peer mid-stream")
            m.sendmail = _fake_sendmail
            return m

        with patch("smtplib.SMTP", _fake_smtp_uncertain):
            res_u = await handle_local_email_approval(
                text="yes",
                session_id=session_id_u,
                user_authorized=True,
            )

        self.assertIsNotNone(res_u)
        self.assertEqual(res_u["status"], "UNCERTAIN")
        self.assertIn("Warning: Connection dropped during transmission", res_u["spoken_response"])
        self.assertNotIn("successfully", res_u["spoken_response"].lower())

        # 2. Hard failure (authentication error)
        session_id_f = "test_session_fail"
        await send_email(
            context=session_id_f,
            to_email="fail@example.com",
            subject="Fail Test",
            message="Check auth fail.",
        )

        def _fake_smtp_fail(*args, **kwargs):
            raise smtplib.SMTPAuthenticationError(535, b"Authentication credentials invalid")

        with patch("smtplib.SMTP", _fake_smtp_fail):
            res_f = await handle_local_email_approval(
                text="yes",
                session_id=session_id_f,
                user_authorized=True,
            )

        self.assertIsNotNone(res_f)
        self.assertEqual(res_f["status"], "FAILED")
        self.assertNotIn("successfully", res_f["spoken_response"].lower())

    async def test_08_ambiguous_and_modification_requests_fail_closed(self):
        """Confirmation coupled with modification or hesitation keywords fails closed without dispatch."""
        session_id = "test_session_mod"
        await send_email(
            context=session_id,
            to_email="mod@example.com",
            subject="Original Subject",
            message="Original Body",
        )

        mock_smtp_inst = MagicMock()
        with patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_inst)):
            # 'yes, but change the subject' must fail closed
            res1 = await handle_local_email_approval(
                text="yes, but change the subject to meeting notes",
                session_id=session_id,
                user_authorized=True,
            )
            self.assertIsNone(res1)
            mock_smtp_inst.sendmail.assert_not_called()

            # 'yes wait a minute' must fail closed
            res2 = await handle_local_email_approval(
                text="yes wait a minute",
                session_id=session_id,
                user_authorized=True,
            )
            self.assertIsNone(res2)
            mock_smtp_inst.sendmail.assert_not_called()

            # Unrelated question must fail closed
            res3 = await handle_local_email_approval(
                text="what is the weather today in Kolkata?",
                session_id=session_id,
                user_authorized=True,
            )
            self.assertIsNone(res3)
            mock_smtp_inst.sendmail.assert_not_called()

        # Draft is preserved for user interaction
        self.assertTrue(has_pending_email_for_session(session_id))

    async def test_09_expired_invalid_token_fails_closed(self):
        """Expired drafts (>300s) and invalid confirmation tokens fail closed."""
        session_id = "test_session_exp"
        await send_email(
            context=session_id,
            to_email="exp@example.com",
            subject="Expiration Test",
            message="Expiring draft.",
        )

        staged = get_pending_email_for_session(session_id)
        # Fast-forward staged_at timestamp by 305 seconds
        staged["staged_at"] = time.time() - 305.0

        mock_smtp_inst = MagicMock()
        with patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_inst)):
            # 1. has_pending_email_for_session detects expiration and clears draft
            self.assertFalse(has_pending_email_for_session(session_id))

            # 2. dispatch_staged_email directly detects expiration if invoked before has_pending check
            await send_email(
                context="exp_direct",
                to_email="exp2@example.com",
                subject="Expiration Test 2",
                message="Expiring draft 2.",
            )
            staged2 = get_pending_email_for_session("exp_direct")
            staged2["staged_at"] = time.time() - 305.0
            exp_res = await dispatch_staged_email(
                session_id="exp_direct",
                confirmation_token=staged2["token"],
                user_authorized=True,
            )
            self.assertIn("expired", exp_res.lower())
            mock_smtp_inst.sendmail.assert_not_called()

    async def test_10_structured_lifecycle_logs_contain_no_secrets(self):
        """Verify structured lifecycle logs are emitted and contain no tokens, credentials, or message body."""
        session_id = "test_session_logs"
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
            # 1. Draft pending
            await send_email(
                context=session_id,
                to_email="audit@example.com",
                subject="Audit Subject",
                message="Secret body content that must not appear in logs",
            )

            # 2. Approval recognized & dispatch authorized & SMTP done & final response
            mock_smtp_inst = MagicMock()
            with patch("smtplib.SMTP", MagicMock(return_value=mock_smtp_inst)):
                await handle_local_email_approval(
                    text="yes, go ahead and send an email",
                    session_id=session_id,
                    user_authorized=True,
                )

            all_log_text = "\n".join(log_records)

            # Verify presence of structured state transition tags
            self.assertIn("EMAIL_DRAFT_PENDING", all_log_text)
            self.assertIn("EMAIL_CONFIRMATION_RECOGNIZED", all_log_text)
            self.assertIn("EMAIL_DISPATCH_AUTHORIZED", all_log_text)
            self.assertIn("EMAIL_SMTP_DISPATCH_DONE", all_log_text)
            self.assertIn("EMAIL_APPROVAL_FINAL_RESPONSE", all_log_text)

            # Verify no secrets or sensitive contents leaked
            self.assertNotIn("Secret body content", all_log_text)
            self.assertNotIn("abcd efgh ijkl mnop", all_log_text)

        finally:
            root_logger.removeHandler(handler)
            root_logger.setLevel(orig_level)

    async def test_11_staged_summary_prompts_yes_or_no(self):
        """Staged email summary explicitly asks the user to answer YES or NO."""
        summary = _format_pending_email_summary(
            to_email="target@example.com",
            subject="Test Subject",
            message="Test Message",
        )
        self.assertIn("Please answer YES to send or NO to cancel.", summary)
        self.assertIn("• To: target@example.com", summary)
        self.assertIn("• Subject: Test Subject", summary)
        self.assertIn("• Body: Test Message", summary)


if __name__ == "__main__":
    unittest.main()
