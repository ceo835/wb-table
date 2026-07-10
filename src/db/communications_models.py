from __future__ import annotations

from datetime import date, datetime
from typing import Any
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.compiler import compiles

from src.db.base import Base

# Teach SQLite how to compile PostgreSQL JSONB type in unit tests
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

# Teach SQLite how to compile BigInteger as INTEGER for autoincrement compatibility
@compiles(BigInteger, "sqlite")
def compile_bigint_sqlite(type_, compiler, **kw):
    return "INTEGER"


class Campaign(Base):
    """Кампания рассылки."""
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    marketplace: Mapped[str] = mapped_column(String(50), nullable=False)  # 'wb' / 'ozon'
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    campaign_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'price_increase', 'promo', 'custom'
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    promocode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    filters_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class ChatRegistry(Base):
    """Единый реестр чатов, полученных из API маркетплейсов."""
    __tablename__ = "chat_registry"
    __table_args__ = (
        UniqueConstraint("marketplace", "chat_id", name="uq_chat_registry_marketplace_chat_id"),
        Index("idx_chat_registry_marketplace_chat", "marketplace", "chat_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    marketplace: Mapped[str] = mapped_column(String(50), nullable=False)  # 'wb' / 'ozon'
    chat_id: Mapped[str] = mapped_column(String(128), nullable=False)
    first_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sender: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reply_sign: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_chat_exists: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False, server_default="false")
    product_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # Список nmID, связанных с чатом
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CampaignRecipient(Base):
    """Получатели конкретной кампании."""
    __tablename__ = "campaign_recipients"
    __table_args__ = (
        UniqueConstraint("campaign_id", "chat_id", name="uq_campaign_recipients_camp_chat"),
        Index("idx_campaign_recipients_campaign", "campaign_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(50), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    recipient_status: Mapped[str] = mapped_column(String(50), nullable=False, default="ready", server_default="ready")  # 'ready', 'test_only', 'unknown', 'excluded', 'sent', 'error'
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SendLog(Base):
    """Лог фактических отправок для аудита."""
    __tablename__ = "send_logs"
    __table_args__ = (
        Index("idx_send_logs_campaign", "campaign_id"),
        Index("idx_send_logs_chat", "chat_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True)
    marketplace: Mapped[str] = mapped_column(String(50), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(128), nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    send_status: Mapped[str] = mapped_column(String(50), nullable=False)  # 'pending', 'sent', 'error', 'skipped'
    api_response: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
