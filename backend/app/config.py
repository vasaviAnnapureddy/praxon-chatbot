r"""
===============================================================================
 config.py — the one door to all settings
===============================================================================

    backend/.env  (secrets)        client/company.yaml  (company info)
              \                      /
               \                    /
                ->   config.py   <-          every other file asks THIS file
                        |
        settings.GEMINI_API_KEY        company.name
        settings.DATABASE_URL          company.whatsapp_link

THE THREE KINDS OF INFORMATION IN THIS PROJECT — do not mix them up:

    .env          = SECRETS.   API keys, database address. Never goes to GitHub.
    company.yaml  = SETTINGS.  Things the CODE needs: colours, chips, numbers.
    .md files     = KNOWLEDGE. What the CHATBOT answers from. Not in this file
                    at all — those go ingest.py -> embeddings -> pgvector.

    Q: Why not let each file read .env and company.yaml itself?
    A: Three reasons. It re-reads the file from disk on every visitor message
       (slow). Rename one YAML key and you must fix 20 files (fragile). And
       nobody can answer "where does the WhatsApp number come from?" (messy).

-------------------------------------------------------------------------------
 WHAT YOU MUST FILL IN TO MAKE THIS WORK
-------------------------------------------------------------------------------
 Copy backend/.env.example to backend/.env, then fill these:

   REQUIRED (nothing works without them):
     DATABASE_URL     Neon pooled connection string (must contain "-pooler")
     GEMINI_API_KEY   from aistudio.google.com/apikey

   REQUIRED before you deploy:
     JWT_SECRET       python -c "import secrets; print(secrets.token_urlsafe(48))"
     APP_ENV          set to "production" on Render

   OPTIONAL (features switch off quietly without them):
     RESEND_API_KEY + ALERT_TO_EMAIL   -> no lead alert emails
     ANTHROPIC_API_KEY / OPENAI_API_KEY -> only if you switch LLM_PROVIDER

   Everything else already has a sensible default. Leave it alone.
===============================================================================
"""

# =============================================================================
# PYTHON NOTES — read once, then the whole file makes sense
# =============================================================================
#
#  list[str]        a list holding strings -> ["Under ₹50,000", "₹5 lakh+"]
#  dict[str, Any]   a dictionary: keys are strings, values can be anything
#  -> list[str]     "this function hands back a list of strings"
#                   Python does NOT enforce it. It is a note for you and for
#                   VS Code, which uses it to autocomplete and warn you.
#  str | None       "either text, or nothing"
#  x or []          if x is empty/None, use [] instead
#  f"{a} and {b}"   builds text with values dropped in
#  self             "this particular object" — how a method reaches its own data
#  _name            the underscore means "private, other files don't touch"
#
#  @property        a method you call WITHOUT brackets.
#                       company.name()   <- looks like an action
#                       company.name     <- looks like a value
#
#     Q: Why bother? Writing "@property" is MORE typing than writing "()".
#     A: You write the decorator once. `name` is read 20 times in this project.
#        But the real reason is bugs: if you forget the brackets on a method,
#        Python does NOT complain. It hands back the function itself, and your
#        system prompt becomes:
#            "You are <bound method Company.bot_name of <object at 0x...>>"
#        No error. No warning. You find out in the meeting. With @property
#        there are no brackets to forget, so that bug cannot exist.
#
#     Q: When should I NOT use @property?
#     A: Three rules. If it is slow, use brackets — brackets are a warning
#        label saying "work happens here". If it changes something, use
#        brackets. If it needs input, you have no choice.
#        That is why pricing_lines() has brackets: it loops and builds a list.
# =============================================================================

from __future__ import annotations          # lets us write `str | None` instead of Optional[str]

import logging                              # used once: warn if company.yaml has a typo
from functools import lru_cache             # "remember the answer, don't redo the work"
from pathlib import Path                    # handles Windows \ and Linux / for us
from typing import Any, Literal             # Any = anything; Literal = only these exact values

import yaml                                 # reads .yaml files into Python dictionaries
from pydantic_settings import BaseSettings, SettingsConfigDict   # auto-reads .env instead of like reading the same code again and again and making a queue for that code within seconds we can complete reading the code. 


# =============================================================================
# SECTION 1 — finding our own folders
# =============================================================================
# We must locate client/company.yaml. We cannot hardcode the path, because the
# app might be started from E:\praxon-chatbot, from inside backend\, or from
# /app inside Docker. So we ask Python where THIS file is, and walk up.
#
#     praxon-chatbot/         <- PROJECT_ROOT
#       backend/              <- BACKEND_DIR
#         app/config.py       <- __file__ (this file)
#       client/company.yaml
#       frontend/

# __file__   -> "...\backend\app\config.py"   (where this file sits)
# .resolve() -> turns a short/relative path into the full real one
# .parent    -> "...\backend\app"   (the folder holding it)
# .parent    -> "...\backend"       (one more step up)
BACKEND_DIR = Path(__file__).resolve().parent.parent
# -> E:\praxon-chatbot\backend

PROJECT_ROOT = BACKEND_DIR.parent
# -> E:\praxon-chatbot


# =============================================================================
# SECTION 2 — Settings: everything that comes from .env
# =============================================================================
class Settings(BaseSettings):
    """Holds every secret and technical switch. Read as `settings.NAME`."""

    # Instructions handed to pydantic about where and how to read .env.
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",   # the "/" joins folders — not division
        env_file_encoding="utf-8",       # so ₹, Telugu and Hindi survive
        extra="ignore",                  # unknown line in .env -> ignore, don't crash
    )

    # -------------------------------------------------------------------------
    # HOW EVERY LINE BELOW WORKS
    #
    #     NAME: type = default
    #     pydantic looks for NAME in .env, converts it to that type, and falls back to the default if it is missing.
    #     .env has:        GEMINI_API_KEY=AIzaSy123
    #     this line says:  GEMINI_API_KEY: str = ""
    #     you then read:   settings.GEMINI_API_KEY   -> "AIzaSy123"
    #
    #   Q: Why does it also matter that it reads real environment variables?
    #   A: On Render there is no .env file — you type values into Render's dashboard instead. Same code, no changes. That is how one codebase
    #      runs both on your laptop and online.
    # -------------------------------------------------------------------------

    # --- which mode are we in -------------------------------------------------
    # Literal = only these two words allowed. "prod" would refuse to start.
    # Worth it: that typo would otherwise leave your API docs page public.
    APP_ENV: Literal["local", "production"] = "local"
    DEBUG: bool = True                  # true = detailed logs while building

    # --- database -------------------------------------------------------------
    #   Q: Why is the default empty? Shouldn't it crash if missing?
    #   A: No — the app must still start so the website works. Only the chat
    #      fails, saying "something went wrong on my side" with a WhatsApp
    #      button. That is the error you saw before making .env. Not a bug.
    DATABASE_URL: str = ""

    # --- which AI ------------------------------------------------------------
    # Change this one word and the whole app talks to a different AI company.
    # No other file changes. Gemini is default: one free key gives us both the
    # chat AI and the multilingual embeddings (Telugu question -> English answer).
    LLM_PROVIDER: Literal["gemini", "claude", "openai"] = "gemini"

    GEMINI_API_KEY: str = ""                          # aistudio.google.com/apikey
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"       # fastest Flash, cheapest
    GEMINI_EMBED_MODEL: str = "gemini-embedding-001"  # text -> numbers, supports task_type
    #   Q: Why did these change? Old ones: gemini-2.0-flash, then 2.5-flash-lite.
    #   A: Google retires models, and new accounts only get the newest ones.
    #      A valid key + a dead model name = chat still fails (404 NOT_FOUND).
    #      To see what YOUR key can use, ask Google: client.models.list()
    #      Check ai.google.dev/gemini-api/docs/models if Google retires these too.

    ANTHROPIC_API_KEY: str = ""                     # only if LLM_PROVIDER=claude
    CLAUDE_MODEL: str = "claude-haiku-4-5"

    OPENAI_API_KEY: str = ""                        # only if LLM_PROVIDER=openai
    OPENAI_MODEL: str = "gpt-4o-mini"

    # How many numbers are in one embedding.
    #
    #   "Do you build mobile apps?"    -> [0.12, -0.44, 0.91, ...]  768 numbers
    #   "Can you make an Android app?" -> [0.13, -0.41, 0.89, ...]  very close
    #                                                               = same meaning
    #
    # !! Do NOT change this after running ingest.py. The database column is
    # built for exactly 768. Numbers from another model cannot be compared with
    # these — like measuring some things in kg and others in litres. Changing it
    # means deleting the documents table and re-ingesting everything.
    EMBED_DIM: int = 768

    # --- email ---------------------------------------------------------------
    # Resend, not Gmail: Render's free plan blocks the ports email normally
    # uses. Gmail would not error — it would silently never send, and you would
    # find out on pitch day.
    RESEND_API_KEY: str = ""
    ALERT_FROM_EMAIL: str = "onboarding@resend.dev"  # until you verify a domain
    ALERT_TO_EMAIL: str = ""                         # your email now, founder's later
    ALERTS_ENABLED: bool = True                      # off while testing

    # --- admin login ---------------------------------------------------------
    # When you log in, the server gives your browser a "pass" signed with this
    # secret, so it can later check the pass is genuine and was not edited.
    # Leave the default online and anyone knowing it could forge a pass and
    # read every visitor's contact details.
    JWT_SECRET: str = "dev-only-insecure-secret"
    ADMIN_SESSION_HOURS: int = 12

    # --- "Continue with Google" ----------------------------------------------
    # From Google Cloud Console -> Credentials -> OAuth client ID (Web app).
    # Looks like: 1234567890-abc123.apps.googleusercontent.com
    #   Q: Isn't this a secret? It's in the .env file.
    #   A: No — Google designs it to be public; it is sent to every browser. It
    #      only says WHICH app is asking. Empty = the Google button is hidden
    #      and username/password login still works.
    GOOGLE_CLIENT_ID: str = ""

    # --- safety limits -------------------------------------------------------
    # Your demo link is public. Without a cap, one bot could send 50,000
    # messages overnight and finish your free AI quota — then Praxon opens the
    # link next morning and it is dead. Message 501 gets a polite reply and the
    # contact buttons, costing nothing.
    DAILY_LLM_CALL_CAP: int = 500

    # Which websites may embed our chat widget.
    #   "*" = anyone (right for a demo — you want to paste it anywhere)
    #   "https://praxontech.in" = only that site
    ALLOWED_EMBED_ORIGINS: str = "*"

    # --- where other folders are ---------------------------------------------
    # Written relative to the backend folder. Settings, not hardcoded, so you
    # can keep one copy of the code and several client folders later.
    CLIENT_DIR: str = "../client"
    FRONTEND_DIST: str = "../frontend/dist"

    # =========================================================================
    # Properties — values we work out, not values you type
    # =========================================================================

    @property
    def client_path(self) -> Path:
        """Turns the setting "../client" into a real full folder path."""
        # Path("../client") — still relative, not usable yet.
        p = Path(self.CLIENT_DIR)
        # is_absolute() -> True if you typed a FULL path like "D:\other-client".
        # If so, respect it. Otherwise glue it onto BACKEND_DIR and tidy it up.
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()
        # -> E:\praxon-chatbot\client        (on Render: /app/client)

    @property
    def content_path(self) -> Path:
        """The folder holding the .md knowledge files. ingest.py reads this."""
        # "/" joins folder names. It is NOT division — Path redefines it.
        return self.client_path / "content"
        # -> E:\praxon-chatbot\client\content

    @property
    def frontend_dist_path(self) -> Path:
        """Where the built React website lives after `npm run build`."""
        # main.py checks this folder. Files there -> FastAPI serves the website.
        # Missing -> it runs API-only and prints a hint in the terminal.
        p = Path(self.FRONTEND_DIST)
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()
        # -> E:\praxon-chatbot\frontend\dist

    @property
    def is_production(self) -> bool:
        """A yes/no answer to "are we live?". Used to hide the API docs page."""
        #   Q: Why not just write settings.APP_ENV == "production" everywhere?
        #   A: Then the word "production" is spelled out in 6 files. Spell it
        #      wrong once and that file silently thinks it is local, forever.
        return self.APP_ENV == "production"
        # -> False on your laptop, True on Render

    @property
    def sqlalchemy_url(self) -> str:
        """Adds the driver name to Neon's connection string. Saves you an hour."""
        # THE PROBLEM: Neon gives you  postgresql://user:pass@ep-xxx...
        # SQLAlchemy needs to be told WHICH DRIVER speaks to the database.
        # Ours is called psycopg. So the string must become:
        #                             postgresql+psycopg://user:pass@ep-xxx...
        #                                       ^^^^^^^^
        # We do it here so you can paste Neon's string EXACTLY as given — no editing, no chance of deleting a character. Everything else in the
        # string, including ?sslmode=require, is left untouched.

        url = self.DATABASE_URL.strip()          # strip() removes stray spaces
        if url.startswith("postgresql+"):        # already has a driver -> leave it
            return url
        if url.startswith("postgresql://"):      # the normal Neon shape
            # replace(old, new, 1) — the 1 means "only the first occurrence",
            # so a password containing "postgresql://" could never be mangled.
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        if url.startswith("postgres://"):        # older short form
            return url.replace("postgres://", "postgresql+psycopg://", 1)
        return url                               # anything else -> hand back as-is


# =============================================================================
# SECTION 3 — Company: everything from company.yaml
# =============================================================================
# yaml.safe_load() turns your file into a plain Python dictionary:
#
#     company:                      {
#       name: "Praxon Technologies"     "company": {"name": "Praxon Technologies"},
#     contacts:                         "contacts": {"sales_email": "hello@..."}
#       sales_email: "hello@..."    }
#
#   Q: Why wrap the dictionary in a class instead of using it directly?
#   A: Safety. Imagine the morning of the pitch: you open company.yaml to
#      change a colour and delete the WhatsApp line by accident.
#        raw dictionary -> chatbot CRASHES, live, in front of the client
#        this class     -> WhatsApp button quietly does not appear, rest works
#      That is why every lookup below has a fallback value.
# =============================================================================
class Company:
    """A forgiving wrapper over client/company.yaml. Never crashes on a missing key."""

    def __init__(self, data: dict[str, Any]) -> None:
        """Runs once when the object is made. Just holds onto the dictionary."""
        self._d = data      # underscore = private, use the methods below instead

    def get(self, dotted: str, default: Any = None) -> Any:
        """Looks up a nested value using a dotted path. Returns default if missing."""
        # INSTEAD OF:  data["contacts"]["sales_email"]     <- crashes if missing
        # WE WRITE:    company.get("contacts.sales_email", "")

        node: Any = self._d                 # start at the top of the dictionary
        for part in dotted.split("."):      # "contacts.sales_email" -> ["contacts","sales_email"]
            # Two ways this can fail, both handled by this one line:
            #   not a dict  -> you asked to go deeper into plain text
            #   not in node -> that key does not exist
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]               # step one level down
        return node

        # WALKING "contacts.sales_email":
        #   start   node = {"company": {...}, "contacts": {...}}
        #   step 1  node = {"sales_email": "hello@praxontech.in", ...}
        #   step 2  node = "hello@praxontech.in"      <- returned

    # -------------------------------------------------------------------------
    # SHORTCUTS
    # The dotted path is written ONCE here, correctly. Everywhere else in the
    # app just writes `company.name`. Typo a path and you silently get the
    # default forever — so it should exist in exactly one place.
    # -------------------------------------------------------------------------

    @property
    def name(self) -> str:
        """The company name. Used in 20 places across the project."""
        # Fallback reads properly in a sentence: "I'm the assistant for the company."
        return self.get("company.name", "the company")
        # -> "Praxon Technologies"

    @property
    def legal_name(self) -> str:
        """The full registered name."""
        # Fallback is another property: leave legal_name blank in the YAML and
        # it politely uses the short name instead of showing an empty space.
        return self.get("company.legal_name", self.name)
        # -> "Praxon Technologies Private Limited"

    @property
    def bot_name(self) -> str:
        """What the assistant calls itself."""
        return self.get("chat.bot_name", "Assistant")
        # -> "Praxon Assistant"

    @property
    def careers_email(self) -> str:
        """Given for every job question. Makes job seekers skip the sales flow."""
        return self.get("contacts.careers_email", "")
        # -> "careers@praxontech.in"

    @property
    def sales_email(self) -> str:
        """The address a real customer is given."""
        return self.get("contacts.sales_email", "")
        # -> "hello@praxontech.in"

    @property
    def whatsapp_link(self) -> str:
        """Builds a full wa.me link from the plain number in the YAML."""
        # WHY THIS ISN'T JUST A LOOKUP: the YAML holds "919000000000" and a
        # message. A browser needs a full link with the message encoded
        # (spaces -> %20, commas -> %2C). Done once here, not in the chat,
        # the dashboard and the email separately.

        number = str(self.get("contacts.whatsapp_number", "")).strip()
        if not number:          # no number -> no button. Forgiving, not crashing.
            return ""
        text = str(self.get("contacts.whatsapp_prefill", "")).strip()

        # Imported inside the function because only this one property needs it —
        # no point slowing down app startup for something rarely used.
        from urllib.parse import quote       # quote() does the %20 encoding

        return f"https://wa.me/{number}?text={quote(text)}" if text else f"https://wa.me/{number}"
        # -> "https://wa.me/919000000000?text=Hi%20Praxon%2C%20I%20came%20from..."

    @property
    def booking_url(self) -> str:
        """The Cal.com / Calendly link for booking a call."""
        return self.get("contacts.booking_url", "")
        # -> "https://cal.com/praxon/intro-call"

    @property
    def budget_options(self) -> list[str]:
        """Budget buttons shown in the chat. Returns a list of strings."""
        # or []   YAML gives None for an empty key; None breaks list(), [] doesn't
        # list()  makes a copy, so callers can't accidentally edit our stored data
        return list(self.get("lead_capture.budget_options", []) or [])
        # -> ['Under ₹50,000', '₹50,000 – ₹2 lakh', '₹2 – ₹5 lakh', '₹5 lakh+', 'Not sure yet']

    @property
    def timeline_options(self) -> list[str]:
        """Timeline buttons. Whatever is tapped becomes a factual label, never a score."""
        return list(self.get("lead_capture.timeline_options", []) or [])
        # -> ['Within a month', '1 to 3 months', '3+ months', 'Just exploring']

    @property
    def ask_order(self) -> list[str]:
        """The order details are collected in: easiest first, most personal last."""
        # Asking a stranger for a phone number first feels pushy. Asking what
        # they want to build feels like interest.
        # The long fallback means the bot still behaves if this section is deleted.
        return list(
            self.get("lead_capture.ask_order", ["requirement", "budget", "timeline", "contact"])
            or []
        )
        # -> ['requirement', 'timeline', 'budget', 'name', 'contact']

    @property
    def quick_questions(self) -> list[str]:
        """Buttons shown the moment the chat opens. Their answers get cached."""
        # First visitor who taps one waits for the AI. Everyone after gets it
        # instantly with no AI call — faster for them, cheaper for you.
        return list(self.get("chat.quick_questions", []) or [])
        # -> ['What services do you offer?', 'How much does a website cost?', ...]

    def pricing_lines(self) -> list[str]:
        """The ONLY prices the assistant may say. Note the brackets — this builds a list."""
        # THE DANGER THIS PREVENTS: the AI invents "₹45,000", Praxon then quotes
        # ₹1,20,000. Lost client, embarrassed founder. These exact lines go into
        # the AI's instructions with a rule that nothing else may be stated.

        rows = self.get("pricing_ranges", []) or []
        out: list[str] = []                 # start empty, fill it up
        for row in rows:
            # pricing_ranges has one odd entry — the disclaimer — with no
            # "service" or "range". This check skips it, so the disclaimer
            # never turns into a nonsense price line.
            if isinstance(row, dict) and "service" in row and "range" in row:
                out.append(f"{row['service']}: {row['range']}")
        return out
        # -> ['Business website (5-8 pages): ₹35,000 – ₹1,20,000', ... 5 lines]

        #   Q: Why brackets here when `name` has none?
        #   A: This does real work — it loops and builds a new list every call.
        #      Brackets are the warning label for that. `name` just fetches.

    @property
    def pricing_disclaimer(self) -> str:
        """The sentence added whenever a price is mentioned. Not optional."""
        # Protects Praxon: a visitor must never be able to say "your website
        # told me it would be ₹35,000".
        rows = self.get("pricing_ranges", []) or []
        for row in rows:
            if isinstance(row, dict) and "disclaimer" in row:
                return str(row["disclaimer"])
        return "These are typical ranges, not quotes."       # if someone deletes it
        # -> "These are typical ranges, not quotes. The real number depends on scope..."

    def as_dict(self) -> dict[str, Any]:
        """Hands back the whole YAML. Used by /api/config to send colours to the browser."""
        return self._d


# =============================================================================
# SECTION 4 — the doors other files actually use
# =============================================================================
#
#   Q: What does @lru_cache do here?
#   A: "Run this once, then remember the answer."
#        without it -> every visitor message re-opens and re-parses the YAML
#        with it    -> read once, every later call is instant
#      maxsize=1 means there is only ever one answer worth remembering.
# =============================================================================


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Creates the Settings object. This is the moment .env is actually read."""
    return Settings()


# The remembered copy of company.yaml, plus WHEN the file was last saved at the
# moment we read it. Starts empty; filled on the first call.
_company_cache: dict[str, Any] = {"mtime": None, "company": None}


def get_company() -> Company:
    """Reads client/company.yaml — but only again if the file changed since last time."""
    #   Q: get_settings uses @lru_cache. Why not this one?
    #   A: lru_cache remembers FOREVER. Edit company.yaml while the server runs
    #      and nothing changes until a restart — this really happened: a new
    #      WhatsApp number was saved, the site kept showing the old one.
    #      Now we remember the file's "last saved" time and re-read only when it
    #      changes. Checking that time is a few microseconds, so it stays fast.
    #      (.env still needs a restart — secrets should not change mid-flight.)

    # 1. Ask settings where the client folder is, then add the filename.
    path = get_settings().client_path / "company.yaml"

    # 2. Check it exists. A clear error now saves twenty minutes of confusion
    #    later — it names the exact path checked and the setting to fix.
    if not path.exists():
        raise FileNotFoundError(
            f"company.yaml not found at {path}. Check CLIENT_DIR in backend/.env."
        )

    # 3. Unchanged since last read? Hand back the remembered copy. No disk read.
    mtime = path.stat().st_mtime                  # -> 1758262912.53 (seconds)
    if _company_cache["company"] is not None and _company_cache["mtime"] == mtime:
        return _company_cache["company"]

    # 4. First call, or the file was saved again -> read it.
    #    "r"              = read only
    #    encoding="utf-8" = so ₹, Telugu and Hindi characters survive
    #    with ...         = closes the file automatically, even if it errors
    try:
        with path.open("r", encoding="utf-8") as fh:
            # safe_load, never load: plain `load` can be tricked into RUNNING code
            # hidden inside a YAML file. safe_load only ever produces plain data.
            # or {} -> an empty file gives None; {} keeps the app alive on defaults.
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        #   Q: What if I save the file with a mistake in it (wrong indent)?
        #   A: Keep serving the LAST GOOD version and log the problem, rather
        #      than taking the whole site down over one bad space.
        if _company_cache["company"] is not None:
            logging.getLogger("config").error(
                "company.yaml has an error — still using the last good version: %s", exc
            )
            return _company_cache["company"]
        raise                                     # no good version yet -> fail loudly

    # 5. Wrap it so every lookup is safe, and remember it with its save time.
    _company_cache["mtime"] = mtime
    _company_cache["company"] = Company(data)
    return _company_cache["company"]


def reload_company() -> Company:
    """Forces a fresh read of company.yaml. Rarely needed now — kept for scripts."""
    _company_cache["company"] = None
    return get_company()


# =============================================================================
# THE LAST LINE — what you will actually use
# =============================================================================
#     from app.config import settings, get_company
#
#     settings.GEMINI_API_KEY      -> your key
#     settings.content_path        -> E:\praxon-chatbot\client\content
#
#     company = get_company()
#     company.name                 -> "Praxon Technologies"
#     company.quick_questions      -> ['What services do you offer?', ...]
#
#   Q: Why is `settings` ready-made but `company` a function call?
#   A: Settings never change while the app runs. The company YAML might,
#      because you edit it and call reload_company(). Calling get_company()
#      each time means you always get the current version.
# =============================================================================
settings = get_settings()
