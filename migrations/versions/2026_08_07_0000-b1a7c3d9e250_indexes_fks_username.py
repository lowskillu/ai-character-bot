"""indexes, foreign keys, drop username uniqueness

Three separate problems:

1. ``profiles.user_id`` had no index, yet it is filtered on almost every
   update. Every profile lookup was a sequential scan.

2. ``profile_message_history`` had two single-column indexes, but every real
   query filters ``user_id`` AND ``profile_id`` and then sorts by
   ``created_at DESC LIMIT 10``. Neither index served that; a composite does,
   and it makes both of the old ones redundant.

3. ``users.username`` was UNIQUE. Telegram frees usernames and reassigns them,
   so as soon as one user took another's old @name, DatabaseMiddleware raised
   IntegrityError on *every* message from them and the bot went silent for
   that person.

Note on the foreign keys: this will fail if orphan rows exist, which is the
intended behaviour — better a loud failure than silently deleting a user's
characters. Check first with:

    SELECT COUNT(*) FROM profiles p
     LEFT JOIN users u ON u.id = p.user_id WHERE u.id IS NULL;
    SELECT COUNT(*) FROM profile_message_history h
     LEFT JOIN users u ON u.id = h.user_id WHERE u.id IS NULL;

Revision ID: b1a7c3d9e250
Revises: 8bf01a721319
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1a7c3d9e250"
down_revision: Union[str, None] = "8bf01a721319"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. profiles ------------------------------------------------------
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"])
    op.create_foreign_key(
        "fk_profiles_user_id_users",
        "profiles",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- 2. profile_message_history ---------------------------------------
    # Serves "WHERE user_id = ? AND profile_id = ? ORDER BY created_at DESC".
    op.execute(
        "CREATE INDEX ix_pmh_user_profile_created "
        "ON profile_message_history (user_id, profile_id, created_at DESC)"
    )
    # Both old indexes are now redundant: user_id is a prefix of the composite,
    # and nothing queries profile_id on its own.
    op.drop_index("ix_profile_message_history_user_id", "profile_message_history")
    op.drop_index("ix_profile_message_history_profile_id", "profile_message_history")

    op.create_foreign_key(
        "fk_pmh_user_id_users",
        "profile_message_history",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_pmh_profile_id_profiles",
        "profile_message_history",
        "profiles",
        ["profile_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- 3. users.username ------------------------------------------------
    # Named by SQLAlchemy's default convention for a column-level unique=True.
    op.drop_constraint("users_username_key", "users", type_="unique")
    # Lookups by username (the /addpremium admin command) still need to be fast.
    op.create_index("ix_users_username", "users", ["username"])


def downgrade() -> None:
    op.drop_index("ix_users_username", "users")
    op.create_unique_constraint("users_username_key", "users", ["username"])

    op.drop_constraint("fk_pmh_profile_id_profiles", "profile_message_history", type_="foreignkey")
    op.drop_constraint("fk_pmh_user_id_users", "profile_message_history", type_="foreignkey")
    op.create_index(
        "ix_profile_message_history_profile_id", "profile_message_history", ["profile_id"]
    )
    op.create_index(
        "ix_profile_message_history_user_id", "profile_message_history", ["user_id"]
    )
    op.drop_index("ix_pmh_user_profile_created", "profile_message_history")

    op.drop_constraint("fk_profiles_user_id_users", "profiles", type_="foreignkey")
    op.drop_index("ix_profiles_user_id", "profiles")
