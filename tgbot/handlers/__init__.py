"""Import all routers and add them to routers_list."""
from .admin import admin_router
from .menu import menu_router
from .user import user_router
from .dialogue_continiur import dialogue_router
from .photo import photo_router
from .premium_grant import premium_router
from .style import style_router
from .customization import customization_router
from .customization_body import customization_body_router
from .customization_options import customization_options_router
from .visual_vnesnost import visual_vnesnost_router
from .fallback import fallback_router

# Order matters: the first router with a matching handler wins.
#
# Specific-to-general. The profile wizard now sits ABOVE user_router, because
# user_router's free-text chat handler would otherwise claim the wizard's input.
# fallback_router must stay last — its handler matches every message.
routers_list = [
    admin_router,
    menu_router,
    premium_router,
    # Wizard first: it owns text and callbacks while a customization state is set.
    customization_router,
    customization_body_router,
    # clothing / personality / location / role — four structurally identical
    # modules collapsed into one table-driven router.
    customization_options_router,
    visual_vnesnost_router,
    photo_router,
    dialogue_router,
    style_router,
    # Free-text chat: StateFilter(None), so it only sees stateless messages.
    user_router,
    # Must remain last.
    fallback_router,
]

__all__ = [
    "routers_list",
]
