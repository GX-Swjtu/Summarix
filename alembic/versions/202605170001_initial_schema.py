"""初始化业务数据库结构

Revision ID: 202605170001
Revises:
Create Date: 2026-05-17 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "202605170001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"], unique=True)
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("adk_session_id", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=True),
        sa.Column("page_title", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversations_adk_session_id"), "conversations", ["adk_session_id"], unique=True)
    op.create_index(op.f("ix_conversations_user_id"), "conversations", ["user_id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("adk_invocation_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_adk_invocation_id"), "messages", ["adk_invocation_id"], unique=False)
    op.create_index(op.f("ix_messages_conversation_id"), "messages", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_messages_trace_id"), "messages", ["trace_id"], unique=False)

    op.create_table(
        "message_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_filename", sa.String(length=320), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=True),
        sa.Column("page_title", sa.String(length=500), nullable=True),
        sa.Column("text_excerpt", sa.Text(), nullable=True),
        sa.Column("text_length", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("adk_invocation_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_message_artifacts_adk_invocation_id"), "message_artifacts", ["adk_invocation_id"], unique=False)
    op.create_index(op.f("ix_message_artifacts_conversation_id"), "message_artifacts", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_message_artifacts_message_id"), "message_artifacts", ["message_id"], unique=False)
    op.create_index(op.f("ix_message_artifacts_trace_id"), "message_artifacts", ["trace_id"], unique=False)
    op.create_index(op.f("ix_message_artifacts_user_id"), "message_artifacts", ["user_id"], unique=False)

    op.create_table(
        "user_model_preferences",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("primary_model_id", sa.String(length=120), nullable=True),
        sa.Column("primary_thinking_mode", sa.String(length=20), nullable=False),
        sa.Column("text_summary_model", sa.String(length=120), nullable=True),
        sa.Column("conversation_model", sa.String(length=120), nullable=True),
        sa.Column("xiaohongshu_model", sa.String(length=120), nullable=True),
        sa.Column("short_video_script_model", sa.String(length=120), nullable=True),
        sa.Column("suggested_questions_model", sa.String(length=120), nullable=True),
        sa.Column("text_summary_thinking_mode", sa.String(length=20), nullable=False),
        sa.Column("conversation_thinking_mode", sa.String(length=20), nullable=False),
        sa.Column("xiaohongshu_thinking_mode", sa.String(length=20), nullable=False),
        sa.Column("short_video_script_thinking_mode", sa.String(length=20), nullable=False),
        sa.Column("suggested_questions_thinking_mode", sa.String(length=20), nullable=False),
        sa.Column("theme", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_model_preferences_user_id"),
    )

    op.create_table(
        "message_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("adk_invocation_id", sa.String(length=120), nullable=True),
        sa.Column("rating", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("langwatch_annotation_id", sa.String(length=120), nullable=True),
        sa.Column("langwatch_sync_status", sa.String(length=30), nullable=False),
        sa.Column("langwatch_sync_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "message_id", name="uq_message_feedback_user_message"),
    )
    op.create_index(op.f("ix_message_feedback_adk_invocation_id"), "message_feedback", ["adk_invocation_id"], unique=False)
    op.create_index(op.f("ix_message_feedback_conversation_id"), "message_feedback", ["conversation_id"], unique=False)
    op.create_index(op.f("ix_message_feedback_message_id"), "message_feedback", ["message_id"], unique=False)
    op.create_index(op.f("ix_message_feedback_trace_id"), "message_feedback", ["trace_id"], unique=False)
    op.create_index(op.f("ix_message_feedback_user_id"), "message_feedback", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_message_feedback_user_id"), table_name="message_feedback")
    op.drop_index(op.f("ix_message_feedback_trace_id"), table_name="message_feedback")
    op.drop_index(op.f("ix_message_feedback_message_id"), table_name="message_feedback")
    op.drop_index(op.f("ix_message_feedback_conversation_id"), table_name="message_feedback")
    op.drop_index(op.f("ix_message_feedback_adk_invocation_id"), table_name="message_feedback")
    op.drop_table("message_feedback")

    op.drop_table("user_model_preferences")

    op.drop_index(op.f("ix_message_artifacts_user_id"), table_name="message_artifacts")
    op.drop_index(op.f("ix_message_artifacts_trace_id"), table_name="message_artifacts")
    op.drop_index(op.f("ix_message_artifacts_message_id"), table_name="message_artifacts")
    op.drop_index(op.f("ix_message_artifacts_conversation_id"), table_name="message_artifacts")
    op.drop_index(op.f("ix_message_artifacts_adk_invocation_id"), table_name="message_artifacts")
    op.drop_table("message_artifacts")

    op.drop_index(op.f("ix_messages_trace_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_conversation_id"), table_name="messages")
    op.drop_index(op.f("ix_messages_adk_invocation_id"), table_name="messages")
    op.drop_table("messages")

    op.drop_index(op.f("ix_conversations_user_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_adk_session_id"), table_name="conversations")
    op.drop_table("conversations")

    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_token_hash"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")