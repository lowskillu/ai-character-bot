"""Router registration order.

Order decides which handler wins. Two regressions this pins down:

* a bare ``@user_router.message()`` catch-all sat in user_router, which is
  registered before customization_router, so everything typed during the
  profile wizard was swallowed and the wizard's text input was unreachable;
* photo_router's trigger had no state filter and sat third, so trigger words
  hijacked messages mid-wizard.
"""

from tgbot.handlers import routers_list
from tgbot.handlers.customization import customization_router
from tgbot.handlers.fallback import fallback_router
from tgbot.handlers.photo import photo_router
from tgbot.handlers.user import user_router


def _index(router):
    return routers_list.index(router)


def test_fallback_router_is_last():
    """It matches every message, so anything after it would be dead."""
    assert routers_list[-1] is fallback_router


def test_wizard_precedes_free_text_chat():
    assert _index(customization_router) < _index(user_router)


def test_photo_router_precedes_free_text_chat():
    assert _index(photo_router) < _index(user_router)


def test_wizard_precedes_photo_trigger():
    assert _index(customization_router) < _index(photo_router)


def test_no_duplicate_routers():
    assert len(routers_list) == len(set(id(r) for r in routers_list))


def _registered_callback_names():
    """Names of every function registered as a callback_query handler."""
    names = []
    for router in routers_list:
        for handler in router.callback_query.handlers:
            names.append(handler.callback.__name__)
    return names


def test_only_one_handler_owns_customize_appearance():
    """It was registered in both customization.py and visual_vnesnost.py.

    Inspecting magic-filter internals is brittle, so this asserts on the
    registered handler functions instead.
    """
    names = _registered_callback_names()
    assert names.count("handle_customize_appearance") == 1


# Admin access is covered behaviourally in test_admin_access.py — aiogram's
# root-filter storage is private and shifts between versions.
