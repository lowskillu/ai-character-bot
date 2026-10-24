"""init

Baseline schema.

This revision shipped with an empty ``upgrade()`` because the old code called
``alembic revision --autogenerate`` at container start, so the real schema was
invented at runtime and never committed (``.gitignore`` also matched
``migrations/versions/``, which is why nothing here was ever tracked).

The body below is what the models describe. Existing deployments are already
stamped at this revision and will skip it; fresh databases run it.

Revision ID: 8bf01a721319
Revises:
Create Date: 2025-07-30 13:50:39.771124

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8bf01a721319'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Matches models.py: created_at/registered_at use a naive UTC server default.
UTC_NOW = sa.text("TIMEZONE('utc', now())")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("registered_at", sa.DateTime(), server_default=UTC_NOW, nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("is_agreement_accepted", sa.Boolean(), nullable=True),
        sa.Column("welcome_sent", sa.Boolean(), nullable=False),
        sa.Column("style", sa.String(), nullable=False),
        sa.Column("premium_level", sa.Integer(), nullable=False),
        sa.Column("premium_until", sa.DateTime(), nullable=True),
        sa.Column("photo_time", sa.String(), nullable=True),
        sa.Column("photo_skin", sa.String(), nullable=True),
        sa.Column("photo_light", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )

    op.create_table(
        "profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("style", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("appearance", sa.String(), nullable=True),
        sa.Column("body_type", sa.String(), nullable=True),
        sa.Column("clothing", sa.String(), nullable=True),
        sa.Column("personality", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=UTC_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "profile_message_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=UTC_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_profile_message_history_user_id", "profile_message_history", ["user_id"]
    )
    op.create_index(
        "ix_profile_message_history_profile_id", "profile_message_history", ["profile_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_profile_message_history_profile_id", "profile_message_history")
    op.drop_index("ix_profile_message_history_user_id", "profile_message_history")
    op.drop_table("profile_message_history")
    op.drop_table("profiles")
    op.drop_table("users")
