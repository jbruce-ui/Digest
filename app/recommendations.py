import os
import anthropic
from .database import get_connection

MODEL = "claude-sonnet-4-6"
MAX_EPISODES_PER_CALL = 100


def get_interests() -> list[dict]:
    with get_connection() as con:
        rows = con.execute(
            "SELECT id, description, created_at FROM interests ORDER BY id"
        ).fetchall()
    return [{"id": r[0], "description": r[1], "created_at": str(r[2])} for r in rows]


def set_interests(descriptions: list[str]) -> list[dict]:
    """Replace all interests with the provided list."""
    with get_connection() as con:
        con.execute("DELETE FROM interests")
        for desc in descriptions:
            desc = desc.strip()
            if desc:
                con.execute(
                    "INSERT INTO interests (id, description) VALUES (nextval('interests_id_seq'), ?)",
                    [desc],
                )
    return get_interests()


def recommend_episodes(episodes: list[dict], interests: list[str], top_n: int = 10) -> list[dict]:
    """Ask Claude to rank episodes by relevance to the user's interests."""
    if not episodes or not interests:
        return []

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    interests_text = "\n".join(f"- {i}" for i in interests)
    episodes_text = "\n\n".join(
        f"[{idx}] {ep['feed_title']} — {ep['title']}\n{ep['description'] or '(no description)'}"
        for idx, ep in enumerate(episodes[:MAX_EPISODES_PER_CALL])
    )

    prompt = f"""You are helping a podcast listener find episodes most relevant to their interests.

User interests:
{interests_text}

Podcast episodes (each prefixed with an index number):
{episodes_text}

Return a JSON array of the top {top_n} most relevant episode indices, ordered from most to least relevant.
Also include a one-sentence reason for each. Use this exact format:
[
  {{"index": 0, "reason": "..."}},
  ...
]
Return only the JSON array, nothing else."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    import json
    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    ranked = json.loads(raw.strip())

    results = []
    for item in ranked:
        idx = item["index"]
        if 0 <= idx < len(episodes):
            ep = dict(episodes[idx])
            ep["reason"] = item.get("reason", "")
            results.append(ep)
    return results
