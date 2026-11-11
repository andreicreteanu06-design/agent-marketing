"""Native workflow configuration, records, runs and delivery outbox.

Revision ID: d91005a7b001
Revises: c8a2d4f6e135
"""
from alembic import op
import sqlalchemy as sa

revision = "d91005a7b001"
down_revision = "c8a2d4f6e135"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("nativeautomation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_account_id", sa.Integer(), sa.ForeignKey("clientaccount.id"), nullable=False),
        sa.Column("workflow", sa.String(30), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("webhook_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("client_account_id", "workflow", name="uq_native_config"))
    op.create_index("ix_nativeautomation_client_account_id", "nativeautomation", ["client_account_id"])
    op.create_table("nativeautomationrecord",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_account_id", sa.Integer(), sa.ForeignKey("clientaccount.id"), nullable=False),
        sa.Column("workflow", sa.String(30), nullable=False),
        sa.Column("external_id", sa.String(160), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("client_account_id", "workflow", "external_id", name="uq_native_record"))
    op.create_index("ix_nativeautomationrecord_client_account_id", "nativeautomationrecord", ["client_account_id"])
    op.create_table("nativeautomationrun",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_account_id", sa.Integer(), sa.ForeignKey("clientaccount.id"), nullable=False),
        sa.Column("workflow", sa.String(30), nullable=False),
        sa.Column("record_id", sa.Integer(), sa.ForeignKey("nativeautomationrecord.id"), nullable=False),
        sa.Column("run_key", sa.String(220), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(25), nullable=False),
        sa.Column("attempt_token", sa.String(36), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_account_id", "workflow", "run_key", name="uq_native_run"))
    for field in ("client_account_id", "record_id", "status"):
        op.create_index(f"ix_nativeautomationrun_{field}", "nativeautomationrun", [field])
    op.create_table("nativeautomationmessage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_account_id", sa.Integer(), sa.ForeignKey("clientaccount.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("nativeautomationrun.id"), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("recipient", sa.String(254), nullable=False),
        sa.Column("subject", sa.String(250), nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("status", sa.String(25), nullable=False),
        sa.Column("requires_review", sa.Boolean(), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("clientuser.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("sending_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.UniqueConstraint("run_id", "step", name="uq_native_message"))
    for field in ("client_account_id", "run_id", "status"):
        op.create_index(f"ix_nativeautomationmessage_{field}", "nativeautomationmessage", [field])


def downgrade():
    for table in ("nativeautomationmessage", "nativeautomationrun", "nativeautomationrecord", "nativeautomation"):
        op.drop_table(table)
