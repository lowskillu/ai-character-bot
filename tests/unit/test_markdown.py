"""MarkdownV2 escaping.

A backslash in the model's output left a dangling escape, Telegram rejected the
message with a 400, and the user got "Failed to generate response" instead of a reply.
"""

import pytest

from tgbot.handlers.user import escape_markdown_v2

SPECIALS = r'_[]()~`>#+-=|{}.!*'


def test_backslash_is_escaped_first():
    assert escape_markdown_v2("a\\b") == "a\\\\b"


def test_backslash_before_special_does_not_produce_dangling_escape():
    # "\*" used to become "\\*" -- an escaped backslash followed by a bare '*'.
    assert escape_markdown_v2("\\*") == "\\\\\\*"


@pytest.mark.parametrize("ch", list(SPECIALS))
def test_every_special_is_escaped(ch):
    assert escape_markdown_v2(ch) == f"\\{ch}"


def test_every_special_char_is_preceded_by_a_backslash():
    """No special character may appear unescaped in the output."""
    text = "".join(SPECIALS) + "\\" + "plain text 123"
    out = escape_markdown_v2(text)

    i = 0
    while i < len(out):
        if out[i] == "\\":
            # An escape must be followed by something.
            assert i + 1 < len(out), f"dangling escape at end of {out!r}"
            i += 2
            continue
        assert out[i] not in SPECIALS, f"unescaped {out[i]!r} at {i} in {out!r}"
        i += 1


def test_plain_text_untouched():
    assert escape_markdown_v2("привет как дела") == "привет как дела"
