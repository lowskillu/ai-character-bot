"""add reference_photo_url to profiles

Revision ID: c3d9e250f421
Revises: b1a7c3d9e250
Create Date: 2026-08-16 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d9e250f421'
down_revision: Union[str, None] = 'b1a7c3d9e250'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('profiles', sa.Column('reference_photo_url', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('profiles', 'reference_photo_url')
