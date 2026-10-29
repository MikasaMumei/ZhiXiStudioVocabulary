"""Shared content resolution and conservative text handling."""
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import select
from .models import Book, Section, Item, Term

FIELDS = ("meaning", "us", "uk", "example", "example_zh")


def initial(spelling):
    """A-Z navigation is a view, never a replacement for textbook units."""
    first = clean(spelling)[:1].upper()
    return first if first in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" and first else "#"


def clean(value):
    return unicodedata.normalize("NFC", "" if value is None else str(value)).strip()


def stamp(source="管理员"):
    return {"source": source, "at": datetime.now(timezone.utc).isoformat()}


def entries(db, book_id=None, ids=None, include_archived=False):
    query = select(Item, Term, Section, Book).join(Term, Item.term_id == Term.id).join(Section, Item.section_id == Section.id).join(Book, Section.book_id == Book.id)
    if not include_archived:
        query = query.where(Item.status != "archived")
    if book_id:
        query = query.where(Book.id == book_id)
    if ids is not None:
        query = query.where(Item.id.in_(ids))
    return db.execute(query.order_by(Book.created_at, Section.position, Item.position, Item.created_at)).all()


def resolved(item, term, section, book):
    data = {field: getattr(item, field) if getattr(item, field) is not None else getattr(term, field) for field in FIELDS}
    data.update(id=item.id, revision=item.revision, term_revision=term.revision, spelling=term.spelling,
                pos=item.pos, notes=item.notes, status=item.status, position=item.position,
                section=section.title, section_code=section.code, section_id=section.id,
                book_id=book.id, book=book.title, book_code=book.code, book_revision=book.revision,
                stage=book.stage, grade=book.grade, publisher=book.publisher, edition=book.edition,
                volume=book.volume, provenance=item.provenance, term_provenance=term.provenance)
    return data


def bump(book):
    book.revision += 1
