import feedparser
import httpx
from datetime import datetime
from typing import Optional
from .database import get_connection


def _parse_published(entry) -> Optional[datetime]:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6])
    return None


def _strip_html(text: str) -> str:
    """Very light HTML tag removal for descriptions."""
    import re
    return re.sub(r"<[^>]+>", "", text or "").strip()


async def fetch_feed_meta(url: str) -> dict:
    """Fetch and parse an RSS feed, returning title and raw entries."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    parsed = feedparser.parse(resp.text)
    title = parsed.feed.get("title", url)
    return {"title": title, "entries": parsed.entries}


def add_feed(url: str, title: str) -> dict:
    with get_connection() as con:
        existing = con.execute(
            "SELECT id, url, title FROM feeds WHERE url = ?", [url]
        ).fetchone()
        if existing:
            return {"id": existing[0], "url": existing[1], "title": existing[2], "created": False}
        row = con.execute(
            "INSERT INTO feeds (id, url, title) VALUES (nextval('feeds_id_seq'), ?, ?) RETURNING id",
            [url, title],
        ).fetchone()
        return {"id": row[0], "url": url, "title": title, "created": True}


def remove_feed(feed_id: int) -> bool:
    with get_connection() as con:
        con.execute("DELETE FROM episodes WHERE feed_id = ?", [feed_id])
        result = con.execute("DELETE FROM feeds WHERE id = ? RETURNING id", [feed_id]).fetchone()
        return result is not None


def list_feeds() -> list[dict]:
    with get_connection() as con:
        rows = con.execute(
            "SELECT id, url, title, created_at FROM feeds ORDER BY id"
        ).fetchall()
    return [{"id": r[0], "url": r[1], "title": r[2], "created_at": str(r[3])} for r in rows]


def store_episodes(feed_id: int, entries: list) -> int:
    """Upsert episodes for a feed; returns count of new episodes added."""
    added = 0
    with get_connection() as con:
        for entry in entries:
            guid = entry.get("id") or entry.get("link", "")
            if not guid:
                continue
            title = entry.get("title", "Untitled")
            description = _strip_html(
                entry.get("summary") or entry.get("description", "")
            )
            link = entry.get("link", "")
            published_at = _parse_published(entry)

            existing = con.execute(
                "SELECT id FROM episodes WHERE guid = ?", [guid]
            ).fetchone()
            if existing:
                continue

            con.execute(
                """INSERT INTO episodes (id, feed_id, guid, title, description, published_at, link)
                   VALUES (nextval('episodes_id_seq'), ?, ?, ?, ?, ?, ?)""",
                [feed_id, guid, title, description, published_at, link],
            )
            added += 1
    return added


def list_episodes(feed_id: Optional[int] = None, limit: int = 200) -> list[dict]:
    with get_connection() as con:
        if feed_id is not None:
            rows = con.execute(
                """SELECT e.id, e.feed_id, f.title as feed_title, e.title, e.description,
                          e.published_at, e.link
                   FROM episodes e JOIN feeds f ON e.feed_id = f.id
                   WHERE e.feed_id = ?
                   ORDER BY e.published_at DESC NULLS LAST LIMIT ?""",
                [feed_id, limit],
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT e.id, e.feed_id, f.title as feed_title, e.title, e.description,
                          e.published_at, e.link
                   FROM episodes e JOIN feeds f ON e.feed_id = f.id
                   ORDER BY e.published_at DESC NULLS LAST LIMIT ?""",
                [limit],
            ).fetchall()
    return [
        {
            "id": r[0],
            "feed_id": r[1],
            "feed_title": r[2],
            "title": r[3],
            "description": r[4],
            "published_at": str(r[5]) if r[5] else None,
            "link": r[6],
        }
        for r in rows
    ]
