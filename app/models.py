"""Persistence models for readers, pages, and volunteer edits."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), index=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    trust: Mapped[int] = mapped_column(Integer, default=50)
    auth_provider: Mapped[str] = mapped_column(String(20), default="email")
    provider_subject: Mapped[str | None] = mapped_column(String(120), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    documents: Mapped[list["Document"]] = relationship(back_populates="owner")
    badges: Mapped[list["BadgeAward"]] = relationship(back_populates="user")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="processing", index=True)
    engine: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    layout_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    image_purge_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    image_purged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    owner: Mapped[User] = relationship(back_populates="documents")
    snippets: Mapped[list["Snippet"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Snippet.sequence",
    )


class Snippet(Base):
    __tablename__ = "snippets"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    original_text: Mapped[str] = mapped_column(Text)
    current_text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="und")
    status: Mapped[str] = mapped_column(String(20), default="extracted", index=True)
    flag_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    flagged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    claimed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    document: Mapped[Document] = relationship(back_populates="snippets")
    claimer: Mapped[User | None] = relationship(foreign_keys=[claimed_by_id])
    edits: Mapped[list["EditHistory"]] = relationship(
        back_populates="snippet",
        cascade="all, delete-orphan",
        order_by="EditHistory.created_at",
    )


class EditHistory(Base):
    __tablename__ = "edit_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    snippet_id: Mapped[int] = mapped_column(ForeignKey("snippets.id", ondelete="CASCADE"), index=True)
    volunteer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    previous_text: Mapped[str] = mapped_column(Text)
    new_text: Mapped[str] = mapped_column(Text)
    review_state: Mapped[str] = mapped_column(String(20), default="live")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    snippet: Mapped[Snippet] = relationship(back_populates="edits")
    volunteer: Mapped[User] = relationship()


class BadgeAward(Base):
    __tablename__ = "badge_awards"
    __table_args__ = (UniqueConstraint("user_id", "badge_key", name="uq_user_badge"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    badge_key: Mapped[str] = mapped_column(String(40))
    awarded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="badges")
