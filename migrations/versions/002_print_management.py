"""Recoverable print management; keep frozen content unchanged."""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column('print_jobs', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('print_jobs', sa.Column('management_revision', sa.Integer(), nullable=False, server_default='1'))
    op.create_index('ix_print_jobs_deleted_created', 'print_jobs', ['deleted_at', 'created_at'])


def downgrade():
    raise RuntimeError('不自动删除管理记录；请按运维流程恢复备份或保留新增字段。')
