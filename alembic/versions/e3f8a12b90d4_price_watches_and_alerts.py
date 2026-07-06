"""price watches and alerts

Revision ID: e3f8a12b90d4
Revises: ca11fc964b29
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e3f8a12b90d4'
down_revision: Union[str, Sequence[str], None] = 'ca11fc964b29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'price_watches',
        sa.Column('origin', sa.String(length=3), nullable=False),
        sa.Column('destination', sa.String(length=3), nullable=False),
        sa.Column('departure_date', sa.Date(), nullable=False),
        sa.Column('return_date', sa.Date(), nullable=True),
        sa.Column('cabin_class', sa.String(), nullable=False),
        sa.Column('target_price_usd', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_price_usd', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('lowest_seen_usd', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('last_alerted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_alerted_price_usd', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_price_watches_active', 'price_watches', ['active', 'departure_date'], unique=False)

    op.create_table(
        'price_alerts',
        sa.Column('watch_id', sa.Uuid(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('price_usd', sa.DECIMAL(precision=10, scale=2), nullable=False),
        sa.Column('previous_price_usd', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('message', sa.String(), nullable=False),
        sa.Column('acknowledged', sa.Boolean(), nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['watch_id'], ['price_watches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_price_alerts_watch', 'price_alerts', ['watch_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_price_alerts_watch', table_name='price_alerts')
    op.drop_table('price_alerts')
    op.drop_index('idx_price_watches_active', table_name='price_watches')
    op.drop_table('price_watches')
