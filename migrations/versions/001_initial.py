"""Frozen initial PostgreSQL schema; never imports live application metadata."""
from alembic import op

revision = "001"
down_revision = None

DDL = [
    """
CREATE TABLE books (
	code VARCHAR(100) NOT NULL, 
	title TEXT NOT NULL, 
	stage VARCHAR(40) NOT NULL, 
	grade VARCHAR(40) NOT NULL, 
	publisher TEXT NOT NULL, 
	edition TEXT NOT NULL, 
	volume TEXT NOT NULL, 
	tags TEXT NOT NULL, 
	revision INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (code)
)
    """,
    """
CREATE TABLE print_jobs (
	title TEXT NOT NULL, 
	snapshot JSONB NOT NULL, 
	documents JSONB NOT NULL, 
	checksum VARCHAR(64) NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)
    """,
    """
CREATE TABLE sources (
	name TEXT NOT NULL, 
	file_hash VARCHAR(64) NOT NULL, 
	details JSONB NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)
    """,
    """
CREATE TABLE terms (
	spelling TEXT NOT NULL, 
	kind VARCHAR(16) NOT NULL, 
	meaning TEXT NOT NULL, 
	us TEXT NOT NULL, 
	uk TEXT NOT NULL, 
	example TEXT NOT NULL, 
	example_zh TEXT NOT NULL, 
	provenance JSONB NOT NULL, 
	revision INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (spelling)
)
    """,
    """
CREATE TABLE import_batches (
	fingerprint VARCHAR(64) NOT NULL, 
	book_id VARCHAR(36), 
	state VARCHAR(20) NOT NULL, 
	files JSONB NOT NULL, 
	raw_archive BYTEA NOT NULL, 
	options JSONB NOT NULL, 
	plan JSONB NOT NULL, 
	report JSONB NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(book_id) REFERENCES books (id)
)
    """,
    """
CREATE INDEX ix_import_batches_fingerprint ON import_batches (fingerprint)
    """,
    """
CREATE TABLE sections (
	book_id VARCHAR(36) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	title TEXT NOT NULL, 
	position INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (book_id, code), 
	FOREIGN KEY(book_id) REFERENCES books (id)
)
    """,
    """
CREATE INDEX ix_sections_book_id ON sections (book_id)
    """,
    """
CREATE TABLE book_items (
	section_id VARCHAR(36) NOT NULL, 
	term_id VARCHAR(36) NOT NULL, 
	position INTEGER NOT NULL, 
	meaning TEXT, 
	pos TEXT NOT NULL, 
	us TEXT, 
	uk TEXT, 
	example TEXT, 
	example_zh TEXT, 
	notes TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	provenance JSONB NOT NULL, 
	origin_id VARCHAR(36), 
	revision INTEGER NOT NULL, 
	id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(section_id) REFERENCES sections (id), 
	FOREIGN KEY(term_id) REFERENCES terms (id)
)
    """,
    """
CREATE INDEX ix_book_items_section_id ON book_items (section_id)
    """,
    """
CREATE INDEX ix_book_items_term_id ON book_items (term_id)
    """,
]

def upgrade():
    for statement in DDL:
        op.execute(statement)

def downgrade():
    raise RuntimeError("不提供破坏性自动降级；请从经过验证的备份恢复。")
