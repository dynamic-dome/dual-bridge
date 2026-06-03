"""parse_codex_output parsing tests (QW1: NDJSON-fallback).

Same style as test_claude_adapter.py: plain asserts + a standalone main().
    python test_codex_adapter.py

Background (QW1, verified 2026-06-02): `codex exec --json` emits NDJSON --
several {..}\\n{..} lines. The old single raw_decode(text) path only sees the
FIRST event (thread.started) and drops the real answer in the last
item.completed / agent_message event. These tests pin the NDJSON path AND the
backward-compatible single-object / pretty-printed / plain-text paths.
"""
from __future__ import annotations

import importlib
import sys


def test_parse_ndjson_multi_event_returns_last_answer() -> None:
    """3-line NDJSON stream -> the answer from the final item.completed event,
    not "" (the old single raw_decode would only see thread.started)."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"type":"thread.started"}\n'
        '{"type":"item.started"}\n'
        '{"type":"item.completed","item":{"text":"DIE ANTWORT"}}\n'
    )
    assert cx.parse_codex_output(raw) == "DIE ANTWORT"
    print("  codex OK — multi-event NDJSON -> last item.completed answer")


def test_parse_ndjson_standard_codex_sequence_skips_turn_completed() -> None:
    """Real codex JSONL commonly ends with turn.completed after the message.
    The parser must skip that non-answer event and return the agent message."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"type":"thread.started","thread_id":"t"}\n'
        '{"type":"turn.started"}\n'
        '{"type":"item.completed","item":{"type":"agent_message","text":"PING"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":1}}\n'
    )
    assert cx.parse_codex_output(raw) == "PING"
    print("  codex OK — standard JSONL sequence skips trailing turn.completed")


def test_parse_single_json_object_unchanged() -> None:
    """A single JSON object stays backward-compatible (no NDJSON misread)."""
    import codex_adapter as cx
    importlib.reload(cx)
    assert cx.parse_codex_output('{"result":"ok"}') == "ok"
    print("  codex OK — single JSON object -> result text (unchanged)")


def test_parse_pretty_printed_single_json_with_newlines() -> None:
    """The critical user-fallback case: an INDENTED single JSON object with
    embedded newlines must NOT be misinterpreted as NDJSON. It decodes once
    (>1 event NOT reached) so the single raw_decode(text) path handles it."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = '{\n  "result": "x"\n}'
    assert cx.parse_codex_output(raw) == "x"
    print("  codex OK — pretty-printed single JSON w/ newlines -> not NDJSON")


def test_parse_plain_text_unchanged() -> None:
    """Plain text without a leading brace is returned verbatim."""
    import codex_adapter as cx
    importlib.reload(cx)
    assert cx.parse_codex_output("just a plain answer") == "just a plain answer"
    print("  codex OK — plain text -> unchanged")


def test_parse_ndjson_with_trailing_hook_noise() -> None:
    """NDJSON plus a trailing non-JSON hook line: the bad line does not decode
    (so it is not counted as an event) but the stream stays usable -- the real
    answer from the last item.completed is still returned."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"type":"thread.started"}\n'
        '{"type":"item.completed","item":{"text":"ROBUST"}}\n'
        'SessionEnd hook failed: not supported\n'
    )
    assert cx.parse_codex_output(raw) == "ROBUST"
    print("  codex OK — NDJSON + trailing hook noise -> still yields the answer")


def test_parse_ndjson_answer_before_trailing_metadata_event() -> None:
    """Codex-Verifier Q3b: a metadata event (turn.completed/usage) AFTER the
    answer must NOT shadow it. reversed(events) hits the metadata event first;
    it carries no real answer key, so it must be skipped -- not stringified via
    json.dumps and returned as if it were the answer."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"type":"thread.started"}\n'
        '{"type":"item.completed","item":{"text":"ECHTE ANTWORT"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":34}}\n'
    )
    assert cx.parse_codex_output(raw) == "ECHTE ANTWORT"
    print("  codex OK — trailing metadata event does not shadow the real answer")


def test_parse_ndjson_trailing_error_event_with_message_does_not_shadow() -> None:
    """Codex-Verifier Q3b round 2: a trailing event that declares a non-answer
    type but carries a stray 'message' key (e.g. an error/status event) must NOT
    shadow the real item.completed answer that came before it."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"type":"item.completed","item":{"text":"DIE ANTWORT"}}\n'
        '{"type":"turn.failed","message":"some status note"}\n'
    )
    assert cx.parse_codex_output(raw) == "DIE ANTWORT"
    print("  codex OK — trailing typed status event w/ message does not shadow")


def test_parse_ndjson_unknown_answer_type_is_not_dropped() -> None:
    """Codex-Verifier Q3b round 3: an answer-bearing event with a type we did NOT
    foresee (e.g. message.output_text.delta) must still be mined for its answer,
    not silently dropped. The denylist only skips KNOWN metadata types."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"type":"thread.started"}\n'
        '{"type":"message.output_text.delta","text":"ZUKUNFTS-ANTWORT"}\n'
        '{"type":"turn.completed","usage":{"output_tokens":3}}\n'
    )
    assert cx.parse_codex_output(raw) == "ZUKUNFTS-ANTWORT"
    print("  codex OK — unbekannter Antwort-Typ wird nicht verworfen (Denylist)")


def test_parse_pretty_printed_json_array_not_misread_as_ndjson() -> None:
    """Codex-Verifier Q3a: a pretty-printed JSON ARRAY (each object on its own
    line) must be parsed as ONE value, not split into NDJSON events. The single
    raw_decode path returns the array's last answer-bearing item."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = '[\n  {"type":"a"},\n  {"result":"FROM ARRAY"}\n]'
    assert cx.parse_codex_output(raw) == "FROM ARRAY"
    print("  codex OK — pretty-printed JSON array -> single value, not NDJSON")


def test_parse_real_codex_0136_ndjson_sequence() -> None:
    """DCO #7729 / P006: pin the BYTE-EXACT event sequence emitted by a REAL
    `codex exec --json` run, not just a hand-guessed fixture.

    Captured 2026-06-03 from codex-cli 0.136.0 on Laptop A
    (`echo "Antworte mit genau dem Wort: PINGPONG" | codex exec --json
    --skip-git-repo-check -s read-only -`). The four real events are:
      thread.started -> turn.started -> item.completed(item.text) -> turn.completed(usage)
    The answer lives in item.completed's item.text; the trailing turn.completed
    (usage) must NOT shadow it. Verified live: parse_codex_output -> "PINGPONG".
    This test fails loudly if a future codex version drifts the schema (the -o
    answer.txt path masks this in production today, QW1)."""
    import codex_adapter as cx
    importlib.reload(cx)
    raw = (
        '{"thread_id":"019e8dbd-81bc-7702-87c9-3f0b1a9242c0","type":"thread.started"}\n'
        '{"type":"turn.started"}\n'
        '{"item":{"id":"item_0","text":"PINGPONG","type":"agent_message"},"type":"item.completed"}\n'
        '{"type":"turn.completed","usage":{"cached_input_tokens":0,"input_tokens":2500,'
        '"output_tokens":7,"reasoning_output_tokens":0}}\n'
    )
    assert cx.parse_codex_output(raw) == "PINGPONG"
    print("  codex OK — REAL codex-0.136 NDJSON sequence -> item.text answer")


def main() -> int:
    print("=== QW1 Codex-Adapter NDJSON-Tests ===")
    tests = [
        test_parse_ndjson_multi_event_returns_last_answer,
        test_parse_ndjson_standard_codex_sequence_skips_turn_completed,
        test_parse_single_json_object_unchanged,
        test_parse_pretty_printed_single_json_with_newlines,
        test_parse_plain_text_unchanged,
        test_parse_ndjson_with_trailing_hook_noise,
        test_parse_ndjson_answer_before_trailing_metadata_event,
        test_parse_ndjson_trailing_error_event_with_message_does_not_shadow,
        test_parse_ndjson_unknown_answer_type_is_not_dropped,
        test_parse_pretty_printed_json_array_not_misread_as_ndjson,
        test_parse_real_codex_0136_ndjson_sequence,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}"); failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}"); failed += 1
    print("=" * 48)
    print(f"{'FEHLER: '+str(failed) if failed else 'Alle'} {len(tests)-failed}/{len(tests)} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
