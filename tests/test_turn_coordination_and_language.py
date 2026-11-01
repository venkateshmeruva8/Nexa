import asyncio
import pytest
from livekit.agents import StopResponse
from backend.actions import (
    detect_explicit_language_switch,
    _extract_app_name,
    _extract_close_app_name,
    COMMON_APPS,
    APP_PROCESS_MAP,
    TurnExecutionCoordinator,
    TurnExecutionRecord,
)

# ============================================================================
# ISSUE 1 TESTS: Language Switching & English Default
# ============================================================================

class TestLanguageHandling:
    def test_explicit_switch_english_commands(self):
        """Explicit English commands to switch language should be detected."""
        test_cases = [
            ("please speak in Telugu", "Telugu", "te-IN"),
            ("switch to Hindi", "Hindi", "hi-IN"),
            ("can you talk in Kannada", "Kannada", "kn-IN"),
            ("speak in Tamil please", "Tamil", "ta-IN"),
            ("change language to Malayalam", "Malayalam", "ml-IN"),
            ("talk in English now", "English", "en-US"),
        ]
        for query, expected_lang, expected_code in test_cases:
            result = detect_explicit_language_switch(query)
            assert result is not None, f"Failed to detect explicit switch for '{query}'"
            lang_name, lang_code, ack = result
            assert lang_name == expected_lang
            assert lang_code == expected_code
            assert len(ack) > 0

    def test_explicit_switch_native_script(self):
        """Native script requests to speak that language should be detected."""
        test_cases = [
            ("తెలుగులో మాట్లాడు", "Telugu", "te-IN"),
            ("हिंदी में बोलो", "Hindi", "hi-IN"),
            ("ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡು", "Kannada", "kn-IN"),
            ("தமிழில் பேசு", "Tamil", "ta-IN"),
        ]
        for query, expected_lang, expected_code in test_cases:
            result = detect_explicit_language_switch(query)
            assert result is not None, f"Failed to detect native switch for '{query}'"
            lang_name, lang_code, ack = result
            assert lang_name == expected_lang
            assert lang_code == expected_code
            assert len(ack) > 0

    def test_multilingual_queries_do_not_switch_language(self):
        """
        Multilingual questions or non-switch queries in Indic scripts or loanwords
        must NOT trigger automatic language switching. Output must remain unchanged.
        """
        non_switch_queries = [
            "what is the time now",
            "open Microsoft Edge",
            "namaste what is the weather today",
            "samayam entha",  # Telugu transliteration for what time is it
            "kya haal hai",    # Hindi transliteration
            "weather kaisa hai",
            "ఈ రోజు వాతావరణం ఎలా ఉంది",  # Telugu for how is weather today
            "आज का मौसम कैसा है",          # Hindi for how is weather today
            "how are you doing",
        ]
        for q in non_switch_queries:
            result = detect_explicit_language_switch(q)
            assert result is None, f"Query '{q}' erroneously triggered language switch!"

    def test_session_language_persistence(self):
        """Coordinator must track response language per session, defaulting to English."""
        coord = TurnExecutionCoordinator()
        assert coord.get_session_language("room_abc") == "English"
        assert coord.get_session_language(None) == "English"

        coord.set_session_language("Telugu", "room_abc")
        assert coord.get_session_language("room_abc") == "Telugu"
        # Other sessions remain English
        assert coord.get_session_language("room_xyz") == "English"
        assert coord.get_session_language(None) == "English"


# ============================================================================
# ISSUE 2 & 3 TESTS: Turn Coordination, Deduplication, & Latency
# ============================================================================

class TestTurnExecutionCoordinator:
    def test_turn_creation_and_distinct_turns(self):
        """Consecutive turns must have distinct identities and execute independently."""
        coord = TurnExecutionCoordinator()
        turn1 = coord.start_turn("turn_1")
        assert turn1.turn_id == "turn_1"
        assert not turn1.action_executed

        # Claim execution for turn 1
        can_exec, is_done, cached = coord.claim_execution("turn_1", "LOCAL_INTENT")
        assert can_exec is True
        assert is_done is False
        coord.record_action_result("turn_1", "LOCAL_INTENT", "It is 1:30 PM.")

        # Consecutive identical user request gets turn_2
        turn2 = coord.start_turn("turn_2")
        assert turn2.turn_id == "turn_2"
        assert not turn2.action_executed

        can_exec2, is_done2, cached2 = coord.claim_execution("turn_2", "LOCAL_INTENT")
        assert can_exec2 is True
        assert is_done2 is False
        assert cached2 is None

    def test_duplicate_action_execution_prevented(self):
        """
        When Local Intent claims execution and records result,
        Gemini Tool on the same turn must receive cached result without re-executing.
        """
        coord = TurnExecutionCoordinator()
        turn_id = "turn_time_001"
        coord.start_turn(turn_id)

        # Local intent claims and executes
        can_exec, is_done, cached = coord.claim_execution(turn_id, "LOCAL_INTENT")
        assert can_exec is True
        coord.record_action_result(turn_id, "LOCAL_INTENT", "The current time is 2:15 PM.")

        # Gemini tool arrives for the same turn
        gemini_can_exec, gemini_is_done, gemini_cached = coord.claim_execution(turn_id, "GEMINI_TOOL")
        assert gemini_can_exec is False, "Gemini tool was allowed to duplicate execution!"
        assert gemini_is_done is True
        assert gemini_cached == "The current time is 2:15 PM."

    def test_gemini_first_local_second(self):
        """
        When Gemini Tool executes first, Local Intent must reuse cached result and not re-execute.
        """
        coord = TurnExecutionCoordinator()
        turn_id = "turn_gemini_first_002"
        coord.start_turn(turn_id)

        # Gemini tool claims and executes
        can_exec, is_done, cached = coord.claim_execution(turn_id, "GEMINI_TOOL")
        assert can_exec is True
        coord.record_action_result(turn_id, "GEMINI_TOOL", "Opened Microsoft Edge successfully.")

        # Local intent checks execution for the same turn
        loc_can_exec, loc_is_done, loc_cached = coord.claim_execution(turn_id, "LOCAL_INTENT")
        assert loc_can_exec is False, "Local intent was allowed to duplicate execution!"
        assert loc_is_done is True
        assert loc_cached == "Opened Microsoft Edge successfully."

    def test_in_progress_execution_locks_out_competing_handler(self):
        """If an action is currently in progress, competing handler must yield."""
        coord = TurnExecutionCoordinator()
        turn_id = "turn_in_progress_003"
        coord.start_turn(turn_id)

        # Handler 1 claims execution
        can_exec, _, _ = coord.claim_execution(turn_id, "LOCAL_INTENT")
        assert can_exec is True

        # Handler 2 attempts to claim while in-progress
        can_exec2, is_done2, cached2 = coord.claim_execution(turn_id, "GEMINI_TOOL")
        assert can_exec2 is False
        assert is_done2 is False
        assert cached2 is None

    def test_spoken_response_deduplication(self):
        """At most one spoken response may be delivered for a single turn."""
        coord = TurnExecutionCoordinator()
        turn_id = "turn_speech_004"
        coord.start_turn(turn_id)

        # First handler claims spoken delivery
        can_speak_1 = coord.claim_spoken_response(turn_id, "LOCAL_INTENT")
        assert can_speak_1 is True

        # Second handler attempts to speak for same turn
        can_speak_2 = coord.claim_spoken_response(turn_id, "GEMINI_SPEECH")
        assert can_speak_2 is False, "Second spoken response was not suppressed!"

    @pytest.mark.asyncio
    async def test_stop_response_on_already_spoken_local_intent_turn(self):
        """
        When Local Intent has already executed and spoken, execute_desktop_action
        must raise StopResponse to cleanly eliminate Gemini tool reply synthesis.
        """
        from backend.tools import execute_desktop_action
        from backend.actions import get_turn_coordinator

        coord = get_turn_coordinator()
        turn_id = "turn_stop_resp_001"
        coord.start_turn(turn_id)
        coord.claim_execution(turn_id, "LOCAL_INTENT")
        coord.record_action_result(turn_id, "LOCAL_INTENT", "Opened WhatsApp.")
        coord.claim_spoken_response(turn_id, "LOCAL_INTENT")

        with pytest.raises(StopResponse):
            await execute_desktop_action(None, "Open WhatsApp")

    @pytest.mark.asyncio
    async def test_normal_tool_return_when_no_local_speech_delivered(self):
        """
        When Local Intent has NOT delivered speech, execute_desktop_action
        must return normal action result without raising StopResponse.
        """
        from backend.tools import execute_desktop_action
        from backend.actions import get_turn_coordinator

        coord = get_turn_coordinator()
        turn_id = "turn_normal_tool_002"
        coord.start_turn(turn_id)

        # Gemini executes directly without prior local intent speech
        result = await execute_desktop_action(None, "Open WhatsApp")
        assert "whatsapp" in result.lower()
        rec = coord.get_or_create_turn(turn_id)
        assert rec.action_executed is True
        assert rec.owner == "GEMINI_TOOL"

    def test_local_confirmation_not_interrupted(self):
        """Local confirmation speech claim must succeed for the originating turn."""
        coord = TurnExecutionCoordinator()
        turn_id = "turn_local_confirm_003"
        coord.start_turn(turn_id)

        can_speak = coord.claim_spoken_response(turn_id, "LOCAL_INTENT")
        assert can_speak is True
        rec = coord.get_or_create_turn(turn_id)
        assert rec.spoken_delivered is True

    def test_normal_gemini_conversational_speech_not_suppressed(self):
        """Conversational turns without local intent execution must authorize Gemini speech freely."""
        coord = TurnExecutionCoordinator()
        turn_id = "turn_convo_004"
        coord.start_turn(turn_id)

        # No local intent ran; Gemini claims speech
        can_speak = coord.claim_spoken_response(turn_id, "GEMINI_SPEECH")
        assert can_speak is True
        rec = coord.get_or_create_turn(turn_id)
        assert rec.spoken_delivered is True

    @pytest.mark.asyncio
    async def test_new_turn_not_affected_by_previous_turn_suppression(self):
        """A new user turn must start with clean state and not inherit previous turn suppression."""
        from backend.tools import execute_desktop_action
        from backend.actions import get_turn_coordinator

        coord = get_turn_coordinator()

        # Turn 1: Local intent executes and speaks
        turn_1 = "turn_isolation_001"
        coord.start_turn(turn_1)
        coord.claim_execution(turn_1, "LOCAL_INTENT")
        coord.record_action_result(turn_1, "LOCAL_INTENT", "Opened Edge.")
        coord.claim_spoken_response(turn_1, "LOCAL_INTENT")

        with pytest.raises(StopResponse):
            await execute_desktop_action(None, "Open Edge")

        # Turn 2: New user turn begins (e.g. conversational question)
        turn_2 = "turn_isolation_002"
        coord.start_turn(turn_2)
        rec_2 = coord.get_or_create_turn(turn_2)
        assert rec_2.action_executed is False
        assert rec_2.spoken_delivered is False
        assert rec_2.owner is None

        # Gemini can claim speech on Turn 2 without suppression
        can_speak_turn_2 = coord.claim_spoken_response(turn_2, "GEMINI_SPEECH")
        assert can_speak_turn_2 is True


# ============================================================================
# ISSUE 2 & 3 TESTS: Browser Suffix Normalization & Launch Resolution
# ============================================================================

class TestBrowserSuffixNormalization:
    def test_browser_suffix_stripped_correctly(self):
        """_extract_app_name must strip 'browser' and 'web browser' suffixes."""
        test_queries = [
            ("open microsoft edge browser", "microsoft edge"),
            ("open edge browser", "edge"),
            ("launch google chrome browser", "google chrome"),
            ("open chrome browser", "chrome"),
            ("open edge web browser", "edge"),
        ]
        for query, expected_app_name in test_queries:
            extracted = _extract_app_name(query)
            assert extracted == expected_app_name, f"Expected '{expected_app_name}', got '{extracted}'"

    def test_browser_aliases_resolve_in_common_apps(self):
        """COMMON_APPS must contain defensive browser aliases mapping to correct executables."""
        assert COMMON_APPS.get("edge") == "msedge"
        assert COMMON_APPS.get("microsoft edge") == "msedge"
        assert COMMON_APPS.get("edge browser") == "msedge"
        assert COMMON_APPS.get("microsoft edge browser") == "msedge"
        assert COMMON_APPS.get("chrome browser") == "chrome"
        assert COMMON_APPS.get("google chrome browser") == "chrome"

    def test_browser_aliases_resolve_in_process_map(self):
        """APP_PROCESS_MAP must correctly map edge and chrome browser variants."""
        assert "msedge.exe" in APP_PROCESS_MAP.get("edge", [])
        assert "msedge.exe" in APP_PROCESS_MAP.get("microsoft edge", [])
        assert "msedge.exe" in APP_PROCESS_MAP.get("edge browser", [])
        assert "msedge.exe" in APP_PROCESS_MAP.get("microsoft edge browser", [])
        assert "chrome.exe" in APP_PROCESS_MAP.get("chrome browser", [])
        assert "chrome.exe" in APP_PROCESS_MAP.get("google chrome browser", [])

    def test_trailing_punctuation_normalized_in_app_name(self):
        """_extract_app_name must strip trailing punctuation like '.', '!', '?'."""
        punct_queries = [
            ("Open Microsoft Edge.", "microsoft edge"),
            ("Open File Explorer.", "file explorer"),
            ("Open WhatsApp.", "whatsapp"),
            ("Open Chrome!", "chrome"),
            ("Open Notepad?", "notepad"),
            ("open microsoft edge browser.", "microsoft edge"),
            ("launch calculator...", "calculator"),
        ]
        for query, expected_app_name in punct_queries:
            extracted = _extract_app_name(query)
            assert extracted == expected_app_name, f"For query '{query}', expected '{expected_app_name}', got '{extracted}'"

    def test_trailing_punctuation_in_close_app_name(self):
        """_extract_close_app_name must strip trailing punctuation."""
        punct_close_queries = [
            ("Close Microsoft Edge.", "microsoft edge"),
            ("Close WhatsApp.", "whatsapp"),
            ("close chrome!", "chrome"),
            ("kill notepad?", "notepad"),
        ]
        for query, expected_app_name in punct_close_queries:
            extracted = _extract_close_app_name(query)
            assert extracted == expected_app_name, f"For query '{query}', expected '{expected_app_name}', got '{extracted}'"

    def test_whatsapp_in_common_apps(self):
        """COMMON_APPS and UWP mapping must support whatsapp."""
        assert "whatsapp" in COMMON_APPS
        assert COMMON_APPS["whatsapp"] == "whatsapp:"
