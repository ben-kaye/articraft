"""SQLite FTS5 is the index AND the search engine. Rebuild by scanning record.json files.

No custom tokenizer, no parallel JSONL index — query the db.
"""

from __future__ import annotations

import re
import sqlite3

from .models import avg_rating
from .records import RecordStore
from .repo import Repo

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS records USING fts5(
    record_id UNINDEXED,
    title,
    prompt,
    category_slug,
    collections UNINDEXED,
    rating UNINDEXED,
    created_at UNINDEXED,
    tokenize = 'porter unicode61'
);
"""

# Connector/boilerplate tokens that shouldn't drive a match. Mirrors the stopword +
# non-distinctive sets in ../articraft/agent/examples.py. "cadquery"/"example(s)" are
# corpus boilerplate — nearly every example doc carries them, so matching on them is noise.
_STOPWORDS = frozenset(
    "a an and as at by for from in into of on or the to with without "
    "cadquery example examples".split()
)


def _fts_query(query: str) -> str:
    """Build an FTS5 MATCH expr from free text: drop boilerplate tokens, OR the rest, and
    prepend the whole phrase so adjacency ranks higher. Each token is quoted so user text
    like "mini-ITX" can't be parsed as FTS operator syntax. Returns "" when nothing's left.
    ponytail: regex tokens + a stopword set, not a real query parser — enough for this corpus.
    """
    terms = re.findall(r"\w+", query.lower())
    kept = [t for t in terms if t not in _STOPWORDS] or terms  # all-stopword query → fall back
    if not kept:
        return ""
    clauses = [f'"{t}"' for t in dict.fromkeys(kept)]  # dedupe, preserve order
    if len(kept) > 1:
        clauses.insert(0, '"' + " ".join(kept) + '"')  # phrase-adjacency boost
    return " OR ".join(clauses)


class Index:
    def __init__(self, repo: Repo):
        self.repo = repo
        self.records = RecordStore(repo)
        self.layout = repo.layout

    def _connect(self) -> sqlite3.Connection:
        self.layout.index_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.layout.index_db)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    def rebuild(self) -> int:
        conn = self._connect()
        try:
            # Every run triggers a rebuild, so parallel runs race here. Serialize them with a
            # single IMMEDIATE transaction (write lock up front + busy_timeout to wait our turn):
            # without it, executescript auto-commits between DROP and INSERT, so concurrent
            # rebuilds interleave and pile up duplicate rows. DROP+recreate (not DELETE) so a
            # tokenizer change in _SCHEMA takes effect — CREATE ... IF NOT EXISTS would skip it.
            conn.isolation_level = None  # manual transaction control
            conn.execute("PRAGMA busy_timeout = 30000")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DROP TABLE IF EXISTS records")
            conn.execute(_SCHEMA)  # single CREATE — execute (not executescript) keeps the txn open
            rows = []
            for rid in self.records.list_ids():
                r = self.records.load(rid)
                rows.append(
                    (
                        rid,
                        r.title,
                        r.prompt,
                        r.category_slug or "",
                        ",".join(r.collections),
                        avg_rating(r.ratings),
                        r.created_at,
                    )
                )
            conn.executemany(
                "INSERT INTO records "
                "(record_id, title, prompt, category_slug, collections, rating, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                rows,
            )
            conn.execute("COMMIT")
            return len(rows)
        finally:
            conn.close()

    def search(self, query: str, limit: int = 50) -> list[str]:
        """Full-text match ranked by FTS5 bm25. Empty query → recent records."""
        conn = self._connect()
        try:
            fts = _fts_query(query)
            if fts:
                cur = conn.execute(
                    "SELECT record_id FROM records WHERE records MATCH ? ORDER BY bm25(records) LIMIT ?",
                    (fts, limit),
                )
            else:
                cur = conn.execute(
                    "SELECT record_id FROM records ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            return [row["record_id"] for row in cur]
        finally:
            conn.close()


_COMBINED_SCHEMA = """
CREATE VIRTUAL TABLE combined USING fts5(
    kind UNINDEXED, ref UNINDEXED, slug, title, body, tokenize = 'porter unicode61'
);
"""

# Per-column bm25 weights (positional, must include UNINDEXED cols). Mirrors the
# field bonuses from ../articraft/agent/examples.py (slug≫title≫body).
_BM25_WEIGHTS = (0.0, 0.0, 6.0, 3.5, 0.5)
_HEADING_RE = re.compile(r"^#\s+(.+)", re.MULTILINE)


class ExampleIndex:
    """One FTS5 table holding the curated sdk/_examples/*.md, ranked by bm25.
    Read from disk and built in-memory.

    search() yields (kind, ref) pairs where kind is always "example" (ref=file path).
    """

    def __init__(self, examples_dir):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_COMBINED_SCHEMA)
        if examples_dir.exists():
            for path in sorted(examples_dir.rglob("*.md")):
                text = path.read_text(encoding="utf-8")
                heading = _HEADING_RE.search(text)
                title = heading.group(1) if heading else path.stem
                self.conn.execute(
                    "INSERT INTO combined (kind, ref, slug, title, body) "
                    "VALUES ('example', ?, ?, ?, ?)",
                    (str(path), path.stem, title, text),
                )
        self.conn.commit()

    def search(self, query: str, limit: int = 50) -> list[tuple[str, str]]:
        """Return (kind, ref) ranked by FTS5 bm25 over examples. Empty query → none."""
        fts = _fts_query(query)
        if not fts:
            return []
        cur = self.conn.execute(
            "SELECT kind, ref FROM combined WHERE combined MATCH ? "
            "ORDER BY bm25(combined, ?, ?, ?, ?, ?) LIMIT ?",
            (fts, *_BM25_WEIGHTS, limit),
        )
        return [(row["kind"], row["ref"]) for row in cur]
