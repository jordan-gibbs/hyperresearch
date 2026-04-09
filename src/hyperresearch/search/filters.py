"""Structured field filter builder for search queries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SearchFilters:
    tags: list[str] | None = None
    status: str | None = None
    note_type: str | None = None
    after: str | None = None
    before: str | None = None
    path_glob: str | None = None
    parent: str | None = None
    min_words: int | None = None
    max_words: int | None = None
    # Graph-aware filters
    linked_from: str | None = None   # Only notes linked FROM this note ID
    linked_to: str | None = None     # Only notes that link TO this note ID
    min_inbound: int | None = None   # Minimum inbound link count
    has_backlinks: bool | None = None # Must have at least one inbound link

    def to_sql(self, table_alias: str = "n") -> tuple[str, list]:
        """Build SQL WHERE clauses and parameters."""
        clauses: list[str] = []
        params: list = []

        if self.tags:
            for tag in self.tags:
                clauses.append(
                    f"{table_alias}.id IN (SELECT note_id FROM tags WHERE tag = ?)"
                )
                params.append(tag.lower())

        if self.status:
            clauses.append(f"{table_alias}.status = ?")
            params.append(self.status)

        if self.note_type:
            clauses.append(f"{table_alias}.type = ?")
            params.append(self.note_type)

        if self.after:
            clauses.append(f"{table_alias}.created >= ?")
            params.append(self.after)

        if self.before:
            clauses.append(f"{table_alias}.created <= ?")
            params.append(self.before)

        if self.path_glob:
            clauses.append(f"{table_alias}.path GLOB ?")
            params.append(self.path_glob)

        if self.parent:
            clauses.append(f"{table_alias}.parent = ?")
            params.append(self.parent)

        if self.min_words is not None:
            clauses.append(f"{table_alias}.word_count >= ?")
            params.append(self.min_words)

        if self.max_words is not None:
            clauses.append(f"{table_alias}.word_count <= ?")
            params.append(self.max_words)

        # Graph-aware filters
        if self.linked_from:
            clauses.append(
                f"{table_alias}.id IN (SELECT target_id FROM links WHERE source_id = ? AND target_id IS NOT NULL)"
            )
            params.append(self.linked_from)

        if self.linked_to:
            clauses.append(
                f"{table_alias}.id IN (SELECT source_id FROM links WHERE target_id = ?)"
            )
            params.append(self.linked_to)

        if self.min_inbound is not None:
            clauses.append(
                f"{table_alias}.id IN (SELECT target_id FROM links WHERE target_id IS NOT NULL "
                f"GROUP BY target_id HAVING COUNT(*) >= ?)"
            )
            params.append(self.min_inbound)

        if self.has_backlinks is True:
            clauses.append(
                f"{table_alias}.id IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL)"
            )

        where = " AND ".join(clauses) if clauses else "1=1"
        return where, params
