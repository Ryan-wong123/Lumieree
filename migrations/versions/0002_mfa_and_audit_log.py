"""two-factor authentication columns and the audit log

Revision ID: 0002_mfa_audit
Revises: 0001_initial
Create Date: 2026-11-08 10:00:00.000000

Expand-only: adds nullable/defaulted columns and a new table, so the previous release keeps working.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_mfa_audit"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("totp_secret", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("mfa_last_step", sa.BigInteger(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "mfa_backup_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_username", sa.String(length=64), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("detail", sa.String(length=255), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_owner_created", "audit_log", ["owner_id", "created_at"], unique=False)
    op.create_index("ix_audit_created", "audit_log", ["created_at"], unique=False)
    op.create_index("ix_audit_action", "audit_log", ["action"], unique=False)


def downgrade():
    op.drop_index("ix_audit_action", table_name="audit_log")
    op.drop_index("ix_audit_created", table_name="audit_log")
    op.drop_index("ix_audit_owner_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_column("users", "mfa_backup_codes")
    op.drop_column("users", "mfa_last_step")
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "totp_secret")
