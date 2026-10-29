"""PostgreSQL storage. Content, original uploads and print artifacts share one backup."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Term(Record, Base):
    __tablename__ = "terms"
    spelling: Mapped[str] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="word")
    meaning: Mapped[str] = mapped_column(Text, default="")
    us: Mapped[str] = mapped_column(Text, default="")
    uk: Mapped[str] = mapped_column(Text, default="")
    example: Mapped[str] = mapped_column(Text, default="")
    example_zh: Mapped[str] = mapped_column(Text, default="")
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Book(Record, Base):
    __tablename__ = "books"
    code: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(40), default="")
    grade: Mapped[str] = mapped_column(String(40), default="")
    publisher: Mapped[str] = mapped_column(Text, default="")
    edition: Mapped[str] = mapped_column(Text, default="未核实")
    volume: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Section(Record, Base):
    __tablename__ = "sections"
    __table_args__ = (UniqueConstraint("book_id", "code"),)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), index=True)
    code: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)


class Item(Record, Base):
    __tablename__ = "book_items"
    section_id: Mapped[str] = mapped_column(ForeignKey("sections.id"), index=True)
    term_id: Mapped[str] = mapped_column(ForeignKey("terms.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    meaning: Mapped[str | None] = mapped_column(Text, nullable=True)
    pos: Mapped[str] = mapped_column(Text, default="")
    us: Mapped[str | None] = mapped_column(Text, nullable=True)
    uk: Mapped[str | None] = mapped_column(Text, nullable=True)
    example: Mapped[str | None] = mapped_column(Text, nullable=True)
    example_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict)
    origin_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Source(Record, Base):
    __tablename__ = "sources"
    name: Mapped[str] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)


class ImportBatch(Record, Base):
    __tablename__ = "import_batches"
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id"), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="draft")
    files: Mapped[list] = mapped_column(JSONB)
    raw_archive: Mapped[bytes] = mapped_column(LargeBinary)
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    plan: Mapped[dict] = mapped_column(JSONB, default=dict)
    report: Mapped[dict] = mapped_column(JSONB, default=dict)


class PrintJob(Record, Base):
    __tablename__ = "print_jobs"
    title: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    documents: Mapped[dict] = mapped_column(JSONB)
    checksum: Mapped[str] = mapped_column(String(64))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    management_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
