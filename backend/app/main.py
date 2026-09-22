"""
===============================================================================
 main.py — the app itself. This is the file uvicorn starts.
===============================================================================

    uvicorn app.main:app --reload --app-dir backend
                |     |
                |     +-- the variable called `app` inside this file
                +-------- this file (backend/app/main.py)

WHAT IT DOES, top to bottom:

    1. set up logging
    2. define what happens on START and STOP        (lifespan)
    3. create the app                               (app = FastAPI(...))
    4. add things that touch EVERY request          (middleware)
    5. plug in the 4 groups of URLs                 (routers)
    6. serve the React website from the same app    (the catch-all)

    Q: Why does ONE app serve both the API and the website?
    A: Render's free plan gives 750 hours a month. A month is at most 744. One always-awake service fits; two do not. So FastAPI serves the built
       React files AND the API together — this is what makes it free.
===============================================================================
"""

# =============================================================================
# PYTHON NOTES — the new ideas in this file
# =============================================================================
#
#  async def / await
#     A normal function makes everyone wait while it works. An async one can pause while waiting (for the database, for Gemini) and let other
#     visitors be served meanwhile. On Render's tiny 0.1 CPU machine, that is the difference between 1 visitor at a time and many.
#         await x   ->  "pause here until x finishes, serve others meanwhile"
#
#  @app.get("/widget.js")
#     A decorator that means: "when a browser asks for this URL, run the function below and send back what it returns." i.e. connects a URL to a Python function and then give what that function says to the url. 
# chatbot hosted at https://yourchatbot.com. clinet website contains <script src="https://yourchatbot.com/widget.js"></script>
# browser says GET /widget.js. fastapi application sees "GET /widget.js" -> @app.get("/widget.js") -> widget_js() -> return widget.js
#  middleware
#     Code that runs on EVERY request, before and after the real handler. Like a security guard every visitor walks past, in and out.
#
#  yield (inside lifespan)
#     Splits a function in two: code BEFORE yield runs when the app starts, code AFTER yield runs when it stops.
#
#  {full_path:path}
#     A URL placeholder that grabs everything, slashes included.
#         /admin/login  ->  full_path = "admin/login"
#
#  Decorator              What it does
#  @property              Method -> attribute-like access
#  @lru_cache             Remember function result
#  @app.get()             URL GET -> function
#  @app.post()            URL POST -> function
#  @app.middleware()      Function -> HTTP middleware
#  @asynccontextmanager   Function -> context manager
#
#  Q: Why is this table written with # and not inside ''' ... '''?
#  A: `from __future__ import ...` must be the FIRST real line of a file. Only
#     the top docstring and # comments may come before it. A second ''' block
#     counts as a real line of code, so Python refuses to run the whole file:
#       SyntaxError: from __future__ imports must occur at the beginning
# =============================================================================

from __future__ import annotations                 # modern type hints

from contextlib import asynccontextmanager         # turns lifespan into a start/stop pair
from pathlib import Path                           # safe folder paths

from fastapi import FastAPI, Request               # the web framework; Request = one incoming visit
from fastapi.middleware.cors import CORSMiddleware # decides which other websites may call us
from fastapi.responses import FileResponse, JSONResponse   # send a file / send JSON
from fastapi.staticfiles import StaticFiles        # serves a whole folder of files

from app.api import admin, auth, chat, health, manage, portal, warmup   # our groups of URLs
from app.config import get_company, settings       # the settings door (see config.py)
from app.core.logging import get_logger, setup_logging    # logs with emails/phones masked
from app.core.security import security_headers     # headers that protect the browser

setup_logging()             # must run first, so everything below can log- like 2026-09-19,Application started,Gemini connected,Visitor opened chat,Lead,Email sentinstead of soemthing happened.
log = get_logger("main")    # log.info("...") now prints lines labelled "main"


# =============================================================================
# STEP 2 — what happens when the app starts and stops
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    """Runs once on start (before yield) and once on stop (after yield)."""

    # --- ON START -------------------------------------------------------------
    # Print which company, mode and AI loaded. On Render this is the FIRST place to look if it booted with the wrong settings.
    company = get_company()
    log.info("=" * 62)                                      # a line of ====
    log.info("  %s assistant starting", company.name)       # %s = drop a value in
    log.info("  env=%s  provider=%s", settings.APP_ENV, settings.LLM_PROVIDER)
    log.info("  client dir: %s", settings.client_path)
    log.info("=" * 62)
    # -> ==============================================================
    #      Praxon Technologies assistant starting
    #      env=local  provider=gemini
    #      client dir: E:\praxon-chatbot\client

    # Finish any lead extraction a previous restart interrupted.
    #   Q: Why is this needed?
    #   A: Render restarts the app whenever it likes. If it restarts halfway
    #      through saving a visitor's details, that lead stays marked "pending"
    #      in the database. This picks it up and finishes it. Nothing is lost.
    #
    #   Q: Why wrapped in try/except?
    #   A: If Neon is asleep or DATABASE_URL is empty, this fails. That must
    #      NOT stop the website from starting. So: warn, and carry on.
    # Windows-only check. uvicorn picks a scheduler the database can't use,
    # UNLESS you start it with --reload. Say so plainly instead of letting the
    # first chat message fail with a 40-line error.
    from app.db.database import uses_windows_proactor
    if uses_windows_proactor():
        log.error("!" * 62)
        log.error("  The database will NOT work in this mode on Windows.")
        log.error("  Stop the server (Ctrl+C) and start it WITH --reload:")
        log.error("  .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --app-dir backend")
        log.error("!" * 62)

    try:
        from app.leads.extractor import retry_pending     # imported here: only needed once
        recovered = await retry_pending()                  # -> 0 normally
        if recovered:
            log.info("recovered %d interrupted lead extractions", recovered)
    except Exception as exc:  # noqa: BLE001
        log.warning("extraction recovery skipped: %s", exc)

    #   Q: Why don't we create the database tables here, on start?
    #   A: Render restarts often. A restart should never be able to change
    #      your database structure. Tables are made by ingest.py, by you, on
    #      purpose.

    yield       # <-- the app is now running and serving visitors

    # --- ON STOP --------------------------------------------------------------
    # Close database connections cleanly, so Neon isn't left holding open ones.
    from app.db.database import dispose_engine
    await dispose_engine()
    log.info("shutdown complete")


# =============================================================================
# STEP 3 — create the app
# =============================================================================
app = FastAPI(
    title="Praxon Website Assistant",
    version="1.0.0",
    lifespan=lifespan,                     # plug in the start/stop code above

    # /docs is an interactive page that lists and tests every API URL.
    # Useful on your laptop. On a public link it is a map for attackers.
    #   is_production -> True on Render -> None -> page switched off
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,                        # a second docs style; never needed
    openapi_url=None if settings.is_production else "/openapi.json",
)


# =============================================================================
# STEP 4 — middleware: runs on EVERY request
# =============================================================================

# --- CORS: which OTHER websites' browsers may call our API --------------------
#   Q: Our site and API are on the same address. Why do we need this at all?
#   A: Two cases. (1) On your laptop, React runs on port 5173 and the API on
#      8000 — different ports count as different sites. (2) When the widget is
#      pasted on a client's website, their domain calls our API.
app.add_middleware(
    CORSMiddleware,
    # "*" -> allow everyone. Otherwise split "a.com,b.com" into ["a.com","b.com"]
    allow_origins=["*"] if settings.ALLOWED_EMBED_ORIGINS == "*"
    else [o.strip() for o in settings.ALLOWED_EMBED_ORIGINS.split(",") if o.strip()],
    allow_credentials=False,               # we never use cookies, so never allow them
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],   # only what we use
    allow_headers=["*"],
)


# --- security headers: stamped onto every response ---------------------------
@app.middleware("http")
async def add_security_headers(request: Request, call_next):  # noqa: ANN001, ANN201
    """Adds protective headers to every response. Rules live in core/security.py."""
    response = await call_next(request)     # let the real handler do its job first
    for key, value in security_headers().items():   # e.g. "X-Content-Type-Options": "nosniff"
        if value:                                   # skip any that are empty
            response.headers[key] = value
    return response


# --- the last safety net: any error nobody else caught -----------------------
@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Never show a visitor a stack trace. Log the real error, send a polite one."""
    #   Q: Why hide the real error? Wouldn't it help to show it?
    #   A: It helps YOU — so it goes to the log. A stack trace shows a visitor
    #      your file paths, library versions and sometimes database details.
    #      That is both ugly and a free map for anyone attacking the site.
    log.exception("unhandled error on %s: %s", request.url.path, exc)   # full detail -> log
    return JSONResponse(
        status_code=500,                                                 # 500 = "server problem"
        content={"detail": "Something went wrong. Please try again in a moment."},
    )


# =============================================================================
# STEP 5 — the 4 groups of URLs. This is EVERYTHING the outside world can reach.
# =============================================================================
app.include_router(health.router)     # /health           keep-alive ping; NEVER touches the DB
app.include_router(warmup.router)     # /api/warmup       wakes Neon when the bubble opens
                                      # /api/config       colours + text for the browser
app.include_router(chat.router)       # /api/chat         the streaming chat
                                      # /api/skip         visitor skipped a lead question
app.include_router(admin.router)      # /api/admin/*      founder dashboard (login required)
app.include_router(auth.router)       # /api/auth/*       log in: team + customers, password + Google
app.include_router(manage.router)     # /api/admin/team, clients, projects   (team only)
app.include_router(portal.router)     # /api/portal/*     customers see ONLY their own projects


# =============================================================================
# STEP 6 — serve the React website from this same app
# =============================================================================
# `npm run build` squeezes the React app into frontend/dist:
#     dist/index.html          the one HTML page
#     dist/assets/*.js, *.css  the compiled code and styles
#     dist/widget.js           the file clients paste into their site

# The company's logo files, from client/brand — NOT from the React build.
#   Q: Why not put the logo in frontend/public like widget.js?
#   A: The rule of this project: everything company-specific lives in client/.
#      Another company = swap client/ (yaml, content, logo). No rebuild, no code.
BRAND: Path = settings.client_path / "brand"
if BRAND.is_dir():
    app.mount("/brand", StaticFiles(directory=BRAND), name="brand")   # StaticFiles refuses "../" too

DIST: Path = settings.frontend_dist_path.resolve()
# -> E:\praxon-chatbot\frontend\dist
# .resolve() matters here: the safety check further down compares full, real
# paths, so DIST itself must be one.

if DIST.exists() and (DIST / "index.html").exists():

    # All of dist/assets served in one line. StaticFiles already refuses "../".
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/widget.js", include_in_schema=False)
    async def widget_js() -> FileResponse:
        """The file clients paste into their site. Cached 5 minutes."""
        # max-age=300 -> browsers reuse it for 300 seconds, then re-check.
        # Short on purpose: when you fix the widget, client sites pick it up fast.
        return FileResponse(
            DIST / "widget.js",
            media_type="application/javascript",
            headers={"Cache-Control": "public, max-age=300"},
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        """Catch-all: real files inside dist are served; any other path gets index.html."""
        # "SPA" = single page app. There is only ONE html page. React reads the
        # URL in the browser and decides whether to show the site, the chat or
        # the dashboard. So /chat, /admin, /admin/login all get index.html.
        #
        #   Q: Why must this route be the LAST one in the file?
        #   A: FastAPI checks routes in the order they are added. This one
        #      matches ANYTHING. Put it above the routers and it swallows
        #      /api/chat — the chatbot would get a web page instead of a reply.

        # Build the full real path the visitor asked for.
        # .resolve() collapses any "../" — so we can see where it REALLY points.
        candidate = (DIST / full_path).resolve()

        # !! SECURITY — do not remove this check !!
        #   Q: Why check is_relative_to(DIST)?
        #   A: "../" means "go up one folder". Without this check, a stranger
        #      could request   /../../backend/.env   and walk out of dist and
        #      download your secrets file. On Render, the same trick can reach
        #      /proc/self/environ — every environment variable, including your
        #      Gemini key and database password. This was a real bug here,
        #      found by testing, and fixed.
        #   is_relative_to(DIST) -> True only if the path is still INSIDE dist.
        if full_path and candidate.is_file() and candidate.is_relative_to(DIST):
            return FileResponse(candidate)          # e.g. /favicon.ico -> the real file

        return FileResponse(DIST / "index.html")    # everything else -> let React decide
        # /admin              -> index.html  (React shows the dashboard)
        # /../../backend/.env -> index.html  (the attack gets a web page, nothing else)

    log.info("serving React build from %s", DIST)

else:
    # No built website — the API still works. This is the mode you are in if
    # frontend/dist is missing and you run `npm run dev` separately.
    log.warning(
        "No React build at %s — API only. Run `npm run dev` in frontend/ for the UI.", DIST
    )

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        """A helpful message instead of a blank 404 on the home page."""
        return {
            "service": "praxon-chatbot API",
            "note": "Frontend not built. Run `npm run dev` in frontend/, or `npm run build`.",
            "health": "/health",
        }
