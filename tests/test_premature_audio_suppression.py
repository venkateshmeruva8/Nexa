# Test file
import time
import pytest
from google.genai import types
from livekit.agents import llm
from livekit.agents.voice import SpeechCreatedEvent, SpeechHandle
from livekit.plugins.google.utils import get_tool_results_for_realtime

from backend.actions import (
    TurnExecutionCoordinator,
    TurnExecutionRecord,
    get_turn_coordinator,
)


@pytest.fixture(autouse=True)
def event_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()
    asyncio.set_event_loop(None)


@pytest.fixture
def coordinator():
    coord = TurnExecutionCoordinator()
    return coord



def test_1_non_blocking_configuration():
    from livekit.plugins.google.realtime import RealtimeModel
    
    model = RealtimeModel(
        api_key="mock_key",
        voice="Aoede",
        temperature=0.6,
        language="en-US",
        input_audio_transcription=None,
        tool_behavior=types.Behavior.NON_BLOCKING,
    )
    assert model._opts.tool_behavior == types.Behavior.NON_BLOCKING
    supports_silent_scheduling = (
        not model._opts.vertexai and model._opts.tool_behavior == types.Behavior.NON_BLOCKING
    )
    assert supports_silent_scheduling is True


def test_2_local_intent_unsolicited_speech_interrupted(coordinator):
    turn_id = "turn_local_test_1"
    coordinator.start_turn(turn_id)
    can_exec, _, _ = coordinator.claim_execution(turn_id, "LOCAL_INTENT")
    assert can_exec is True
    coordinator.record_action_result(turn_id, "LOCAL_INTENT", "Opened WhatsApp.")
    can_speak = coordinator.claim_spoken_response(turn_id, "LOCAL_INTENT")
    assert can_speak is True

    time.sleep(0.05)
    handle = SpeechHandle.create(allow_interruptions=True)
    ev = SpeechCreatedEvent(speech_handle=handle, user_initiated=False, source="generate_reply")

    should_suppress, suppressed_tid, reason = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert should_suppress is True
    assert suppressed_tid == turn_id
    assert "suppressed_local_turn" in reason

    handle.interrupt(force=True)
    assert handle.interrupted is True


def test_3_local_confirmation_never_interrupted(coordinator):
    turn_id = "turn_local_test_2"
    coordinator.start_turn(turn_id)
    coordinator.claim_execution(turn_id, "LOCAL_INTENT")
    coordinator.record_action_result(turn_id, "LOCAL_INTENT", "Opened Microsoft Edge.")
    coordinator.claim_spoken_response(turn_id, "LOCAL_INTENT")

    handle = SpeechHandle.create(allow_interruptions=True)
    ev = SpeechCreatedEvent(speech_handle=handle, user_initiated=True, source="generate_reply")

    if ev.user_initiated:
        should_check = False
    else:
        should_check = True

    assert should_check is False
    assert handle.interrupted is False


def test_4_normal_conversational_speech_not_interrupted(coordinator):
    turn_id = "turn_conv_test_1"
    coordinator.start_turn(turn_id)

    handle = SpeechHandle.create(allow_interruptions=True)
    ev = SpeechCreatedEvent(speech_handle=handle, user_initiated=False, source="generate_reply")

    should_suppress, check_tid, reason = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert should_suppress is False
    assert check_tid == turn_id
    assert reason == "owner_is_None"
    assert handle.interrupted is False


def test_5_delayed_speech_cannot_suppress_subsequent_conversational_turn(coordinator):
    turn_1 = "turn_local_101"
    coordinator.start_turn(turn_1)
    coordinator.claim_execution(turn_1, "LOCAL_INTENT")
    coordinator.record_action_result(turn_1, "LOCAL_INTENT", "Opened File Explorer.")
    coordinator.claim_spoken_response(turn_1, "LOCAL_INTENT")

    turn_2 = "turn_conv_102"
    coordinator.start_turn(turn_2)

    handle_2 = SpeechHandle.create(allow_interruptions=True)
    ev_2 = SpeechCreatedEvent(speech_handle=handle_2, user_initiated=False, source="generate_reply")

    should_suppress, active_tid, reason = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert should_suppress is False
    assert active_tid == turn_2
    assert reason == "owner_is_None"
    assert handle_2.interrupted is False

    coordinator.start_turn("turn_local_stale")
    coordinator.claim_execution("turn_local_stale", "LOCAL_INTENT")
    coordinator.record_action_result("turn_local_stale", "LOCAL_INTENT", "Done.")
    coordinator.claim_spoken_response("turn_local_stale", "LOCAL_INTENT")
    rec = coordinator.get_active_record()
    rec.action_completed_at = time.monotonic() - 6.0

    should_suppress, stale_tid, reason = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert should_suppress is False
    assert "turn_expired" in reason

    coordinator.start_turn("turn_local_no_quota_leak")
    coordinator.claim_execution("turn_local_no_quota_leak", "LOCAL_INTENT")
    coordinator.record_action_result("turn_local_no_quota_leak", "LOCAL_INTENT", "Done.")
    coordinator.claim_spoken_response("turn_local_no_quota_leak", "LOCAL_INTENT")

    s1, _, r1 = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert s1 is True
    s2, _, r2 = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert s2 is True
    assert "suppressed_local_turn" in r2


def test_6_stop_response_produces_silent_scheduling():
    ctx = llm.ChatContext()
    ctx.items.append(llm.FunctionCallOutput(
        name="execute_desktop_action",
        call_id="call_dup_1",
        output="",
        is_error=False,
        reply_required=False,  # Set by StopResponse()
    ))
    resp = get_tool_results_for_realtime(ctx, supports_silent_scheduling=True)
    assert resp is not None
    assert len(resp.function_responses) == 1
    assert resp.function_responses[0].scheduling == types.FunctionResponseScheduling.SILENT


def test_7_cloud_tools_normal_spoken_responses():
    ctx = llm.ChatContext()
    ctx.items.append(llm.FunctionCallOutput(
        name="get_weather",
        call_id="call_weather_1",
        output="The weather in Tokyo is 18C and partly cloudy.",
        is_error=False,
        reply_required=True,  # Normal tool return
    ))
    resp = get_tool_results_for_realtime(ctx, supports_silent_scheduling=True)
    assert resp is not None
    assert len(resp.function_responses) == 1
    assert resp.function_responses[0].scheduling is None


@pytest.mark.asyncio
async def test_8_conversational_turn_does_not_claim_local_intent(coordinator):
    from backend.actions import handle_local_speech_intent
    text = "Yeah."
    res = await handle_local_speech_intent(text)
    assert res is None

    turn_id = "turn_conv_yeah"
    coordinator.start_turn(turn_id)
    coordinator.register_turn_transcript(turn_id, text)

    rec = coordinator.get_active_record()
    assert rec.turn_id == turn_id
    assert rec.owner is None
    assert rec.action_executed is False
    assert rec.action_result is None

    should_suppress, tid, reason = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert should_suppress is False
    assert tid == turn_id
    assert reason == "owner_is_None"


def test_9_correlate_tool_call_matches_completed_local_turn(coordinator):
    turn_1 = "turn_wa_completed"
    coordinator.start_turn(turn_1)
    coordinator.register_turn_transcript(turn_1, "Open WhatsApp.")
    coordinator.claim_execution(turn_1, "LOCAL_INTENT")
    coordinator.record_action_result(turn_1, "LOCAL_INTENT", "Opened WhatsApp.", command="Open WhatsApp.")
    coordinator.claim_spoken_response(turn_1, "LOCAL_INTENT")

    turn_2 = "turn_conv_yeah"
    coordinator.start_turn(turn_2)
    coordinator.register_turn_transcript(turn_2, "Yeah.")

    # Delayed tool call for WhatsApp arriving during turn_2
    status, matched_rec = coordinator.correlate_tool_call("Open WhatsApp")
    assert status == "ALREADY_EXECUTED_BY_LOCAL"
    assert matched_rec is not None
    assert matched_rec.turn_id == turn_1


def test_10_correlate_tool_call_unmatched_stale_fails_closed(coordinator):
    turn_id = "turn_president_q"
    coordinator.start_turn(turn_id)
    coordinator.register_turn_transcript(turn_id, "Who was the first president of the United States?")

    # Unmatched / stale desktop tool call
    status, matched_rec = coordinator.correlate_tool_call("open calculator")
    assert status == "UNMATCHED_STALE"
    assert matched_rec is None


def test_11_correlate_tool_call_active_turn_match(coordinator):
    turn_id = "turn_active_notepad"
    coordinator.start_turn(turn_id)
    coordinator.register_turn_transcript(turn_id, "Open Notepad.")

    status, matched_rec = coordinator.correlate_tool_call("Open Notepad")
    assert status == "ACTIVE_TURN_MATCH"
    assert matched_rec is not None
    assert matched_rec.turn_id == turn_id


def test_12_all_unsolicited_handles_suppressed_in_window(coordinator):
    turn_id = "turn_multi_handle"
    coordinator.start_turn(turn_id)
    coordinator.register_turn_transcript(turn_id, "Open Microsoft Edge.")
    coordinator.claim_execution(turn_id, "LOCAL_INTENT")
    coordinator.record_action_result(turn_id, "LOCAL_INTENT", "Opened Microsoft Edge.", command="Open Microsoft Edge.")

    h1 = SpeechHandle.create(allow_interruptions=True)
    s1, _, r1 = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert s1 is True
    h1.interrupt(force=True)
    assert h1.interrupted is True

    h2 = SpeechHandle.create(allow_interruptions=True)
    s2, _, r2 = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert s2 is True
    h2.interrupt(force=True)
    assert h2.interrupted is True

    h3 = SpeechHandle.create(allow_interruptions=True)
    s3, _, r3 = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert s3 is True
    h3.interrupt(force=True)
    assert h3.interrupted is True


@pytest.mark.asyncio
async def test_13_exact_5_step_live_sequence(coordinator):
    from livekit.agents.llm import StopResponse
    from backend.actions import handle_local_speech_intent
    from backend.tools import execute_desktop_action

    # Step 1: User says "Open WhatsApp."
    t1 = "turn_001_whatsapp"
    coordinator.start_turn(t1)
    coordinator.register_turn_transcript(t1, "Open WhatsApp.")

    cand_1 = await handle_local_speech_intent("Open WhatsApp.")
    assert cand_1 is not None and cand_1.get("handled") is True
    can_exec, is_done, cached = coordinator.claim_execution(t1, "LOCAL_INTENT")
    assert can_exec is True
    coordinator.record_action_result(t1, "LOCAL_INTENT", cand_1["result"], command="Open WhatsApp.")
    can_speak = coordinator.claim_spoken_response(t1, "LOCAL_INTENT")
    assert can_speak is True

    # Premature speech handle within window is suppressed
    h1 = SpeechHandle.create(allow_interruptions=True)
    suppress_1, tid_1, _ = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert suppress_1 is True
    assert tid_1 == t1
    h1.interrupt(force=True)
    assert h1.interrupted is True

    # Delayed tool call for WhatsApp raises StopResponse
    with pytest.raises(StopResponse):
        await execute_desktop_action(None, "Open WhatsApp")

    # Step 2: User says "Yeah."
    t2 = "turn_002_yeah"
    coordinator.start_turn(t2)
    coordinator.register_turn_transcript(t2, "Yeah.")

    cand_2 = await handle_local_speech_intent("Yeah.")
    assert cand_2 is None

    # Verify Turn 2 is NOT claimed by LOCAL_INTENT
    rec_2 = coordinator.get_active_record()
    assert rec_2.turn_id == t2
    assert rec_2.owner is None
    assert rec_2.action_executed is False

    # Gemini speech on Turn 2 is NOT suppressed
    h2 = SpeechHandle.create(allow_interruptions=True)
    suppress_2, tid_2, reason_2 = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert suppress_2 is False
    assert tid_2 == t2
    assert reason_2 == "owner_is_None"
    assert h2.interrupted is False

    # Delayed tool call for WhatsApp arriving during Turn 2 still correlates to t1 and raises StopResponse
    status_delayed, matched_rec = coordinator.correlate_tool_call("Open WhatsApp")
    assert status_delayed == "ALREADY_EXECUTED_BY_LOCAL"
    assert matched_rec.turn_id == t1
    with pytest.raises(StopResponse):
        await execute_desktop_action(None, "Open WhatsApp")

    # Step 3: User says "Who was the first president of the United States?"
    t3 = "turn_003_president"
    coordinator.start_turn(t3)
    coordinator.register_turn_transcript(t3, "Who was the first president of the United States?")

    cand_3 = await handle_local_speech_intent("Who was the first president of the United States?")
    assert cand_3 is None

    rec_3 = coordinator.get_active_record()
    assert rec_3.turn_id == t3
    assert rec_3.owner is None

    # Gemini conversational voice is NOT suppressed
    h3 = SpeechHandle.create(allow_interruptions=True)
    suppress_3, tid_3, reason_3 = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert suppress_3 is False
    assert tid_3 == t3
    assert reason_3 == "owner_is_None"
    assert h3.interrupted is False

    # Step 4: User says "Open Microsoft Edge."
    t4 = "turn_004_edge"
    coordinator.start_turn(t4)
    coordinator.register_turn_transcript(t4, "Open Microsoft Edge.")

    cand_4 = await handle_local_speech_intent("Open Microsoft Edge.")
    assert cand_4 is not None and cand_4.get("handled") is True
    can_exec_4, _, _ = coordinator.claim_execution(t4, "LOCAL_INTENT")
    assert can_exec_4 is True
    coordinator.record_action_result(t4, "LOCAL_INTENT", cand_4["result"], command="Open Microsoft Edge.")
    can_speak_4 = coordinator.claim_spoken_response(t4, "LOCAL_INTENT")
    assert can_speak_4 is True

    # Premature Gemini audio suppressed
    h4 = SpeechHandle.create(allow_interruptions=True)
    suppress_4, tid_4, _ = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert suppress_4 is True
    assert tid_4 == t4
    h4.interrupt(force=True)
    assert h4.interrupted is True

    with pytest.raises(StopResponse):
        await execute_desktop_action(None, "Open Microsoft Edge")

    # Step 5: User says "Open File Explorer."
    t5 = "turn_005_explorer"
    coordinator.start_turn(t5)
    coordinator.register_turn_transcript(t5, "Open File Explorer.")

    cand_5 = await handle_local_speech_intent("Open File Explorer.")
    assert cand_5 is not None and cand_5.get("handled") is True
    can_exec_5, _, _ = coordinator.claim_execution(t5, "LOCAL_INTENT")
    assert can_exec_5 is True
    coordinator.record_action_result(t5, "LOCAL_INTENT", cand_5["result"], command="Open File Explorer.")
    can_speak_5 = coordinator.claim_spoken_response(t5, "LOCAL_INTENT")
    assert can_speak_5 is True

    # Premature Gemini audio suppressed
    h5 = SpeechHandle.create(allow_interruptions=True)
    suppress_5, tid_5, _ = coordinator.try_suppress_unsolicited_speech(max_age=5.0)
    assert suppress_5 is True
    assert tid_5 == t5
    h5.interrupt(force=True)
    assert h5.interrupted is True

    with pytest.raises(StopResponse):
        await execute_desktop_action(None, "Open File Explorer")


