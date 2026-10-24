"""The table-driven wizard screens actually dispatch and store what they claim.

Four modules (clothing / personality / location / role) were structurally
86-92% identical and got collapsed into one table. The keyboard snapshot proves
the rendering did not change; this proves the behaviour did not either — in
particular that the ``F.data.func`` prefix filter really matches, which a static
callback-coverage check cannot show.
"""

import pytest

from tgbot.handlers import customization_options as opts


class FakeState:
    def __init__(self, data=None):
        self.data = dict(data or {})

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kw):
        self.data.update(kw)
        return dict(self.data)


class FakeMessage:
    def __init__(self):
        self.text = None
        self.markup = None

    async def edit_text(self, text, reply_markup=None, parse_mode=None):
        self.text = text
        self.markup = reply_markup


class FakeCall:
    def __init__(self, data):
        self.data = data
        self.message = FakeMessage()
        self.answered = False

    async def answer(self, *_a, **_kw):
        self.answered = True


ALL = sorted(opts.SCREENS)


@pytest.mark.parametrize("name", ALL)
def test_every_screen_declares_both_languages(name):
    screen = opts.SCREENS[name]
    assert set(screen.options) >= {"ru", "en"}
    assert screen.options["ru"] and screen.options["en"]
    # Same values in both languages, only the labels differ. A mismatch would
    # mean a choice made in one language is unrenderable in the other.
    assert [v for _, v in screen.options["ru"]] == [v for _, v in screen.options["en"]]
    assert screen.prompt("ru") != screen.prompt("en"), "prompt is not translated"


@pytest.mark.parametrize("name", ALL)
def test_the_choose_filter_matches_every_rendered_button(name):
    """The dispatch predicate is a lambda; check it against real callback data."""
    predicate = lambda d: isinstance(d, str) and d.startswith(opts.CHOOSE_PREFIXES)  # noqa: E731
    for lang in ("ru", "en"):
        for button in opts.SCREENS[name].keyboard(lang).inline_keyboard:
            for btn in button:
                cb = btn.callback_data
                if cb.endswith("_back"):
                    assert cb in opts.BACK_CALLBACKS
                else:
                    assert predicate(cb), f"{cb} would not reach handle_choose"


@pytest.mark.parametrize("name", ALL)
async def test_choosing_a_value_stores_it_under_the_right_field(name):
    screen = opts.SCREENS[name]
    value = screen.options["ru"][-1][1]
    state = FakeState({"language": "ru", "profile_data": {}})
    call = FakeCall(f"{name}_choose_{value}")

    await opts.handle_choose(call, state)

    assert state.data["profile_data"][screen.field] == value
    assert call.answered, "the button would spin forever"
    assert call.message.text == screen.prompt("ru")


@pytest.mark.parametrize("name", ALL)
async def test_opening_a_screen_marks_the_current_value(name):
    screen = opts.SCREENS[name]
    value = screen.options["en"][0][1]
    state = FakeState({"language": "en", "profile_data": {screen.field: value}})
    call = FakeCall(f"customize_{name}")

    await opts.handle_open(call, state)

    marked = [
        b.text
        for row in call.message.markup.inline_keyboard
        for b in row
        if b.callback_data == f"{name}_choose_{value}"
    ]
    assert marked and marked[0].endswith("✅"), "the saved choice is not shown as selected"


async def test_a_choice_does_not_disturb_other_fields():
    state = FakeState({"language": "ru", "profile_data": {"name": "Саша", "role": "friend"}})
    await opts.handle_choose(FakeCall("clothing_choose_Long-sleeved shirt and trousers"), state)
    assert state.data["profile_data"]["name"] == "Саша"
    assert state.data["profile_data"]["role"] == "friend"
    assert state.data["profile_data"]["clothing"] == "Long-sleeved shirt and trousers"
