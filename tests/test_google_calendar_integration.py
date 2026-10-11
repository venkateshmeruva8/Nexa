import os
import sys
import json
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.mcp.util import FunctionTool
from backend.mcp.agent_tools import (
    MCPToolsIntegration,
    resolve_calendar_id,
    check_and_record_calendar_dispatch,
    _RECENT_CALENDAR_DISPATCHES,
)
import backend.actions as actions


class TestGoogleCalendarIntegration(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        import backend.mcp.agent_tools as at
        at._RECENT_CALENDAR_DISPATCHES.clear()

    def tearDown(self):
        import backend.mcp.agent_tools as at
        at._RECENT_CALENDAR_DISPATCHES.clear()

    def test_01_primary_resolves_to_google_calendar_id_when_configured(self):
        """1. 'primary' resolves to GOOGLE_CALENDAR_ID when configured."""
        with patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "custom_cal@domain.com", "GMAIL_USER": "gmail_user@domain.com"}):
            self.assertEqual(resolve_calendar_id("primary"), "custom_cal@domain.com")
            self.assertEqual(resolve_calendar_id("PRIMARY"), "custom_cal@domain.com")
            self.assertEqual(resolve_calendar_id(""), "custom_cal@domain.com")
            self.assertEqual(resolve_calendar_id(None), "custom_cal@domain.com")

    def test_02_primary_resolves_to_gmail_user_when_google_calendar_id_unset(self):
        """2. 'primary' resolves to GMAIL_USER when GOOGLE_CALENDAR_ID is unset."""
        with patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "", "GMAIL_USER": "gmail_user@domain.com"}):
            self.assertEqual(resolve_calendar_id("primary"), "gmail_user@domain.com")
            self.assertEqual(resolve_calendar_id(None), "gmail_user@domain.com")

    def test_03_explicit_calendar_email_preserved(self):
        """3. An explicitly supplied calendar email is preserved."""
        with patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "cfg_cal@domain.com", "GMAIL_USER": "gmail_user@domain.com"}):
            self.assertEqual(resolve_calendar_id("other_user@example.com"), "other_user@example.com")
            self.assertEqual(resolve_calendar_id("team_shared@group.calendar.google.com"), "team_shared@group.calendar.google.com")

    def test_04_fallback_remains_primary_when_no_config(self):
        """4. The fallback remains 'primary' when neither configuration value exists."""
        with patch.dict(os.environ, {"GOOGLE_CALENDAR_ID": "", "GMAIL_USER": ""}):
            self.assertEqual(resolve_calendar_id("primary"), "primary")
            self.assertEqual(resolve_calendar_id(None), "primary")
            self.assertEqual(resolve_calendar_id(""), "primary")

    async def test_05_direct_calendar_action_uses_same_priority(self):
        """5. The direct calendar action uses the same priority."""
        mock_server = MagicMock()
        mock_server.connect = AsyncMock()
        mock_server.cleanup = AsyncMock()

        mock_invoke = AsyncMock(
            return_value='{"summary": "Team Review", "htmlLink": "https://calendar.google.com/review"}'
        )
        mock_tool = FunctionTool(
            name="Create_an_event_in_Google_Calendar",
            description="Create event",
            params_json_schema={
                "type": "object",
                "properties": {
                    "Calendar": {"type": "string"},
                    "Start": {"type": "string"},
                    "End": {"type": "string"},
                },
            },
            on_invoke_tool=mock_invoke,
        )

        with patch.dict(os.environ, {
            "N8N_MCP_SERVER_URL": "http://localhost:5678/mcp/test",
            "GOOGLE_CALENDAR_ID": "action_cal@domain.com",
            "GMAIL_USER": "fallback@domain.com",
        }), \
             patch("backend.mcp.server.MCPServerSse", return_value=mock_server), \
             patch("backend.mcp.util.MCPUtil.get_function_tools", new_callable=AsyncMock) as mock_gft:
            mock_gft.return_value = [mock_tool]

            res = await actions.execute_calendar_event("Schedule a meeting tomorrow at 11am for Team Review")
            self.assertIn("Team Review", res)
            self.assertIn("successfully created in Google Calendar", res)

            # Check that mock_invoke was called with action_cal@domain.com
            mock_invoke.assert_awaited_once()
            _, call_json_str = mock_invoke.call_args[0]
            parsed = json.loads(call_json_str)
            self.assertEqual(parsed.get("Calendar"), "action_cal@domain.com")

    async def test_06_http_202_produces_accepted_pending_wording(self):
        """6. HTTP 202 produces accepted/pending wording, not a false success or failure."""
        mock_invoke = AsyncMock(return_value='{"message": "Workflow was started"}')
        mock_raw_tool = FunctionTool(
            name="Create_an_event_in_Google_Calendar",
            description="Create event",
            params_json_schema={"type": "object", "properties": {}},
            on_invoke_tool=mock_invoke,
        )

        dec_tool = MCPToolsIntegration._create_decorated_tool(mock_raw_tool)
        fn = getattr(dec_tool, "func", dec_tool)

        res = await fn(
            Calendar="primary",
            Start="2026-10-16 10:00 AM",
            End="2026-10-16 11:00 AM",
            Summary="Async Sync",
        )

        # Must report accepted by scheduling service
        self.assertIn("accepted by the scheduling service", res)
        self.assertIn("Please check your Google Calendar to confirm the event was created", res)
        # Must not claim event was already created
        self.assertNotIn("successfully created", res)
        self.assertNotIn("failed", res.lower())

    async def test_07_genuine_mcp_errors_remain_errors(self):
        """7. Genuine MCP errors remain errors and are not masked."""
        # A. Timeout error
        mock_timeout = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_raw_tool_t = FunctionTool(
            name="Create_an_event_in_Google_Calendar",
            description="Create event",
            params_json_schema={"type": "object", "properties": {}},
            on_invoke_tool=mock_timeout,
        )
        dec_t = MCPToolsIntegration._create_decorated_tool(mock_raw_tool_t)
        fn_t = getattr(dec_t, "func", dec_t)

        res_t = await fn_t(Summary="Timeout Test", Start="2026-10-18 10:00 AM")
        self.assertIn("timed out", res_t.lower())

        # B. Connection error
        mock_conn = AsyncMock(side_effect=ConnectionRefusedError("Port unreachable"))
        mock_raw_tool_c = FunctionTool(
            name="Create_an_event_in_Google_Calendar",
            description="Create event",
            params_json_schema={"type": "object", "properties": {}},
            on_invoke_tool=mock_conn,
        )
        dec_c = MCPToolsIntegration._create_decorated_tool(mock_raw_tool_c)
        fn_c = getattr(dec_c, "func", dec_c)

        res_c = await fn_c(Summary="Conn Test", Start="2026-10-19 10:00 AM")
        self.assertIn("unreachable", res_c.lower())

        # C. Downstream error payload
        mock_err = AsyncMock(return_value='{"error": "Invalid calendar ID: invalid_cal"}')
        mock_raw_tool_e = FunctionTool(
            name="Create_an_event_in_Google_Calendar",
            description="Create event",
            params_json_schema={"type": "object", "properties": {}},
            on_invoke_tool=mock_err,
        )
        dec_e = MCPToolsIntegration._create_decorated_tool(mock_raw_tool_e)
        fn_e = getattr(dec_e, "func", dec_e)

        res_e = await fn_e(Summary="Payload Error Test", Start="2026-10-20 10:00 AM")
        self.assertIn("failed", res_e.lower())
        self.assertIn("Invalid calendar ID", res_e)

    async def test_08_calendar_debounce_still_works(self):
        """8. The existing calendar debounce still works with resolved calendar ID."""
        mock_invoke = AsyncMock(
            return_value='{"summary": "Sprint Retro", "htmlLink": "https://calendar.google.com/retro"}'
        )
        mock_raw_tool = FunctionTool(
            name="Create_an_event_in_Google_Calendar",
            description="Create event",
            params_json_schema={"type": "object", "properties": {}},
            on_invoke_tool=mock_invoke,
        )

        dec_tool = MCPToolsIntegration._create_decorated_tool(mock_raw_tool)
        fn = getattr(dec_tool, "func", dec_tool)

        with patch.dict(os.environ, {"GMAIL_USER": "testuser@gmail.com"}):
            # First call succeeds
            res1 = await fn(
                Calendar="primary",
                Start="2026-10-25 03:00 PM",
                End="2026-10-25 04:00 PM",
                Summary="Sprint Retro",
            )
            self.assertIn("successfully created in Google Calendar", res1)
            self.assertEqual(mock_invoke.await_count, 1)

            # Second call within debounce window is blocked
            res2 = await fn(
                Calendar="primary",
                Start="2026-10-25 03:00 PM",
                End="2026-10-25 04:00 PM",
                Summary="Sprint Retro",
            )
            self.assertIn("Duplicate calendar event creation prevented", res2)
            self.assertEqual(mock_invoke.await_count, 1)


if __name__ == "__main__":
    unittest.main()
