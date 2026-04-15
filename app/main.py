import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from fastapi_mcp import FastApiMCP

from .database import init_db
from . import feeds as feed_service
from . import recommendations as rec_service

load_dotenv()

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Digest",
    description="Podcast episode finder powered by Claude",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class FeedIn(BaseModel):
    url: str


class InterestsIn(BaseModel):
    interests: list[str]


class RecommendIn(BaseModel):
    top_n: int = 10


# ---------------------------------------------------------------------------
# API — Feeds
# ---------------------------------------------------------------------------

@app.get("/api/feeds", tags=["feeds"], summary="List all podcast feeds")
def api_list_feeds():
    """Return all registered podcast feeds."""
    return feed_service.list_feeds()


@app.post("/api/feeds", tags=["feeds"], summary="Add a podcast feed")
async def api_add_feed(body: FeedIn):
    """Add a podcast RSS feed by URL. Fetches the feed title immediately."""
    try:
        meta = await feed_service.fetch_feed_meta(body.url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not fetch feed: {exc}")
    return feed_service.add_feed(body.url, meta["title"])


@app.delete("/api/feeds/{feed_id}", tags=["feeds"], summary="Remove a podcast feed")
def api_remove_feed(feed_id: int):
    """Remove a feed and all its episodes."""
    if not feed_service.remove_feed(feed_id):
        raise HTTPException(status_code=404, detail="Feed not found")
    return {"deleted": feed_id}


@app.post("/api/feeds/{feed_id}/fetch", tags=["feeds"], summary="Fetch episodes for a feed")
async def api_fetch_feed(feed_id: int):
    """Fetch the latest episodes from a feed and store them."""
    all_feeds = feed_service.list_feeds()
    feed = next((f for f in all_feeds if f["id"] == feed_id), None)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    try:
        meta = await feed_service.fetch_feed_meta(feed["url"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not fetch feed: {exc}")
    added = feed_service.store_episodes(feed_id, meta["entries"])
    return {"feed_id": feed_id, "episodes_added": added}


@app.post("/api/feeds/fetch-all", tags=["feeds"], summary="Fetch episodes for all feeds")
async def api_fetch_all_feeds():
    """Fetch latest episodes from every registered feed."""
    results = []
    for feed in feed_service.list_feeds():
        try:
            meta = await feed_service.fetch_feed_meta(feed["url"])
            added = feed_service.store_episodes(feed["id"], meta["entries"])
            results.append({"feed_id": feed["id"], "title": feed["title"], "episodes_added": added})
        except Exception as exc:
            results.append({"feed_id": feed["id"], "title": feed["title"], "error": str(exc)})
    return results


# ---------------------------------------------------------------------------
# API — Episodes
# ---------------------------------------------------------------------------

@app.get("/api/episodes", tags=["episodes"], summary="List stored episodes")
def api_list_episodes(feed_id: Optional[int] = None, limit: int = 200):
    """List episodes, optionally filtered by feed."""
    return feed_service.list_episodes(feed_id=feed_id, limit=limit)


# ---------------------------------------------------------------------------
# API — Interests
# ---------------------------------------------------------------------------

@app.get("/api/interests", tags=["interests"], summary="Get user interests")
def api_get_interests():
    """Return the current list of user interests."""
    return rec_service.get_interests()


@app.put("/api/interests", tags=["interests"], summary="Set user interests")
def api_set_interests(body: InterestsIn):
    """Replace user interests with the provided list."""
    return rec_service.set_interests(body.interests)


# ---------------------------------------------------------------------------
# API — Recommendations
# ---------------------------------------------------------------------------

@app.post("/api/recommend", tags=["recommendations"], summary="Get episode recommendations")
def api_recommend(body: RecommendIn):
    """Ask Claude to recommend episodes based on stored interests and episodes."""
    interests = [i["description"] for i in rec_service.get_interests()]
    if not interests:
        raise HTTPException(status_code=400, detail="No interests set. Add interests first.")
    episodes = feed_service.list_episodes(limit=200)
    if not episodes:
        raise HTTPException(status_code=400, detail="No episodes found. Fetch feeds first.")
    return rec_service.recommend_episodes(episodes, interests, top_n=body.top_n)


# ---------------------------------------------------------------------------
# UI routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def ui_index(request: Request):
    all_feeds = feed_service.list_feeds()
    interests = rec_service.get_interests()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "feeds": all_feeds, "interests": interests},
    )


@app.post("/ui/feeds/add", response_class=RedirectResponse, include_in_schema=False)
async def ui_add_feed(url: str = Form(...)):
    try:
        meta = await feed_service.fetch_feed_meta(url)
        result = feed_service.add_feed(url, meta["title"])
        if result["created"]:
            feed_service.store_episodes(result["id"], meta["entries"])
    except Exception:
        pass
    return RedirectResponse("/", status_code=303)


@app.post("/ui/feeds/{feed_id}/delete", response_class=RedirectResponse, include_in_schema=False)
def ui_delete_feed(feed_id: int):
    feed_service.remove_feed(feed_id)
    return RedirectResponse("/", status_code=303)


@app.post("/ui/feeds/fetch-all", response_class=RedirectResponse, include_in_schema=False)
async def ui_fetch_all():
    for feed in feed_service.list_feeds():
        try:
            meta = await feed_service.fetch_feed_meta(feed["url"])
            feed_service.store_episodes(feed["id"], meta["entries"])
        except Exception:
            pass
    return RedirectResponse("/", status_code=303)


@app.post("/ui/interests", response_class=RedirectResponse, include_in_schema=False)
def ui_set_interests(interests: str = Form(...)):
    lines = [l.strip() for l in interests.splitlines() if l.strip()]
    rec_service.set_interests(lines)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# MCP layer — exposes all API endpoints as MCP tools
# ---------------------------------------------------------------------------

mcp = FastApiMCP(app, name="Digest", description="Podcast episode finder MCP server")
mcp.mount()


@app.get("/ui/recommend", response_class=HTMLResponse, include_in_schema=False)
def ui_recommend(request: Request, top_n: int = 10):
    interests = [i["description"] for i in rec_service.get_interests()]
    episodes = feed_service.list_episodes(limit=200)
    recommendations = []
    error = None
    if not interests:
        error = "Add some interests before getting recommendations."
    elif not episodes:
        error = "No episodes found. Add feeds and fetch them first."
    else:
        try:
            recommendations = rec_service.recommend_episodes(episodes, interests, top_n=top_n)
        except Exception as exc:
            error = str(exc)
    return templates.TemplateResponse(
        "recommend.html",
        {"request": request, "recommendations": recommendations, "error": error},
    )
