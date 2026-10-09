import json


def test_deferred_marker_round_trips_as_provider_valid_tool_result():
    from gateway.extensions.deferred_clarify import (
        DEFERRED_CLARIFY_KIND,
        is_deferred_clarify_result,
        make_deferred_marker,
        parse_deferred_marker,
    )

    marker = make_deferred_marker("cld_123")
    payload = json.loads(marker)

    assert payload["status"] == "deferred"
    assert payload["kind"] == DEFERRED_CLARIFY_KIND
    assert payload["interaction_id"] == "cld_123"
    assert is_deferred_clarify_result(marker) is True
    assert parse_deferred_marker(marker) == "cld_123"


def test_recovery_prompt_includes_question_answer_and_instruction():
    from gateway.extensions.deferred_clarify import build_recovery_prompt

    prompt = build_recovery_prompt(
        question="Deploy where?",
        answer="staging",
    )

    assert "previous Hermes turn" in prompt
    assert "Deploy where?" in prompt
    assert "staging" in prompt
    assert "Do not ask the same clarification again" in prompt


def test_marker_parser_ignores_malformed_or_other_tool_results():
    from gateway.extensions.deferred_clarify import (
        is_deferred_clarify_result,
        parse_deferred_marker,
    )

    assert parse_deferred_marker("not json") is None
    assert parse_deferred_marker('{"status":"ok"}') is None
    assert is_deferred_clarify_result('{"status":"ok"}') is False


def test_finds_marker_inside_actual_clarify_tool_result_envelope():
    from agent.tool_dispatch_helpers import make_tool_result_message
    from gateway.extensions.deferred_clarify import (
        find_deferred_clarify_interaction_id,
        make_deferred_marker,
    )
    from tools.clarify_tool import clarify_tool

    tool_result = clarify_tool(
        question="Deploy where?",
        choices=["staging", "production"],
        callback=lambda _question, _choices: make_deferred_marker("cld_executor_123"),
    )
    messages = [make_tool_result_message("clarify", tool_result, "call_clarify")]

    assert (
        find_deferred_clarify_interaction_id(messages, {"call_clarify"})
        == "cld_executor_123"
    )


def test_deferred_detection_is_constrained_to_clarify_tool_envelope():
    from gateway.extensions.deferred_clarify import (
        find_deferred_clarify_interaction_id,
        make_deferred_marker,
    )
    from tools.clarify_tool import clarify_tool

    marker = make_deferred_marker("cld_other_tool")
    clarify_envelope = clarify_tool(
        question="Deploy where?",
        callback=lambda _question, _choices: marker,
    )

    assert (
        find_deferred_clarify_interaction_id(
            [
                {
                    "role": "tool",
                    "name": "terminal",
                    "tool_call_id": "call_1",
                    "content": clarify_envelope,
                }
            ],
            {"call_1"},
        )
        is None
    )
    assert (
        find_deferred_clarify_interaction_id(
            [
                {
                    "role": "tool",
                    "name": "clarify",
                    "tool_call_id": "call_1",
                    "content": marker,
                }
            ],
            {"call_1"},
        )
        is None
    )


def test_gateway_durable_clarify_persists_telegram_identity(tmp_path):
    from types import SimpleNamespace

    from gateway.run import _create_durable_clarify_interaction
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from tools.clarify_interaction import get_interaction

    token = set_hermes_home_override(tmp_path)
    try:
        interaction, metadata = _create_durable_clarify_interaction(
            session_key="telegram:123:456:789",
            session_id="session-1",
            source=SimpleNamespace(chat_id=123, thread_id=456, user_id=789),
            fallback_chat_id="fallback",
            metadata={"reply_to_message_id": "99"},
            question="Deploy where?",
            choices=["staging", "production"],
        )

        loaded = get_interaction(interaction.interaction_id)
        assert loaded is not None
        assert loaded.platform == "telegram"
        assert loaded.session_id == "session-1"
        assert loaded.chat_id == "123"
        assert loaded.thread_id == "456"
        assert loaded.user_id == "789"
        assert loaded.metadata is not None
        assert loaded.metadata["durable_clarify"] is True
        assert metadata["reply_to_message_id"] == "99"
    finally:
        reset_hermes_home_override(token)


def test_gateway_durable_clarify_send_records_message_and_returns_marker(tmp_path):
    import concurrent.futures
    from types import SimpleNamespace

    from gateway.extensions.deferred_clarify import parse_deferred_marker
    from gateway.run import _durable_clarify_send_result
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from tools.clarify_interaction import create_clarify_interaction, get_interaction

    token = set_hermes_home_override(tmp_path)
    try:
        interaction = create_clarify_interaction(
            session_key="telegram:123",
            platform="telegram",
            question="Deploy where?",
            choices=["staging"],
        )
        future = concurrent.futures.Future()
        future.set_result(SimpleNamespace(success=True, message_id="200"))

        marker = _durable_clarify_send_result(
            future,
            interaction_id=interaction.interaction_id,
        )

        assert parse_deferred_marker(marker) == interaction.interaction_id
        loaded = get_interaction(interaction.interaction_id)
        assert loaded is not None
        assert loaded.status == "pending"
        assert loaded.message_id == "200"
    finally:
        reset_hermes_home_override(token)


def test_gateway_normalization_suppresses_deferred_clarify_no_reply():
    from gateway.run import _normalize_empty_agent_response

    assert _normalize_empty_agent_response(
        {"deferred_clarify_interaction_id": "cld_123", "api_calls": 1},
        "NO_REPLY",
    ) == ""


def test_clear_durable_clarify_prompt_removes_keyboard_by_message_id():
    import asyncio
    from types import SimpleNamespace

    from gateway.run import _clear_durable_clarify_prompt

    calls = []

    class Adapter:
        async def clear_clarify_prompt(self, chat_id, message_id):
            calls.append((chat_id, message_id))

    interaction = SimpleNamespace(
        chat_id="123",
        message_id="456",
        choices=["staging", "production"],
    )
    asyncio.run(_clear_durable_clarify_prompt(Adapter(), interaction))

    assert calls == [("123", "456")]
