"""
Create or reset the founder's dashboard login.

    python backend/scripts/create_admin.py

It asks for the username and password interactively and never takes them as
command-line arguments — arguments end up in your shell history, and this
password protects every visitor's contact details.

Run it once against the dev branch and once against the production branch (change
DATABASE_URL in backend/.env between runs). The two databases are separate, so
they need separate admin rows.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.core.security import hash_password, password_strength_problem  # noqa: E402
from app.db import crud  # noqa: E402
from app.db.database import dispose_engine, get_engine, run, session_scope  # noqa: E402
from app.db.models import Base  # noqa: E402

setup_logging()
log = get_logger("create_admin")


async def ensure_tables() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


async def main() -> None:
    print()
    print("=" * 60)
    print("  Create / reset the admin dashboard login")
    print("=" * 60)
    print(f"  Database: ...@{settings.DATABASE_URL.split('@')[-1][:50]}")
    print()

    # Rules shown BEFORE asking, so nobody learns them by failing.
    print("  Password rules:")
    print("    - at least 12 characters")
    print("    - at least 3 of: lowercase, UPPERCASE, digits, symbols")
    print("    - example shape:  Praxon@Admin2026")
    print()
    print("  Nothing appears on screen while you type the password. That is normal.")
    print("  Do NOT paste with Ctrl+V — in a hidden prompt on Windows it sends one")
    print("  invisible character, not your password. TYPE it, or RIGHT-CLICK to paste.")
    print()

    username = input("  Username (no spaces): ").strip()
    if not username:
        print("  Username cannot be empty.")
        return
    #   Q: Why no spaces? "praxon admin" is a valid name.
    #   A: You must type it exactly at every login. One space too many or too few
    #      and it looks like a wrong password. One word is impossible to get wrong.
    if " " in username:
        print(f"  '{username}' has a space. Use one word, e.g. {username.replace(' ', '')}")
        return

    password = getpass.getpass("  Password (hidden): ")
    confirm = getpass.getpass("  Confirm password: ")

    # Tell them WHAT we received (the length, never the password itself).
    # Without this, a Ctrl+V paste shows up as a mystery "too short" error.
    print(f"\n  Received a password of {len(password)} characters.")
    if len(password) <= 2:
        print("  That looks like a paste that didn't work (Ctrl+V). Type it, or right-click to paste.")

    if password != confirm:
        print("  The two passwords do not match. Nothing was changed.")
        return

    problem = password_strength_problem(password)
    if problem:
        print(f"  {problem}")
        print("  Nothing was changed. This dashboard sits on a public URL.")
        return

    await ensure_tables()
    session = await session_scope()
    try:
        # Owners live in the `users` table now (role "owner"). The old `admins`
        # table is only read once, by upgrade_db.py, to copy existing logins over.
        existing = await crud.find_user_for_login(session, username)
        if existing:
            if existing.role != "owner":
                print(f"\n  '{username}' is a {existing.role} account, not an owner. Nothing changed.")
                return
            answer = input(f"\n  '{username}' already exists. Reset the password? (yes/no): ")
            if answer.strip().lower() not in {"yes", "y"}:
                print("  Cancelled.")
                return
            existing.password_hash = hash_password(password)
            existing.is_active = True
            await session.commit()
            print(f"\n  Password reset for '{username}'.")
        else:
            await crud.create_user(
                session, role="owner", username=username, name=username,
                password_hash=hash_password(password),
            )
            print(f"\n  Owner '{username}' created.")

        print("  Sign in at /admin on your site.")
        print("  To also use 'Continue with Google':")
        print("    python backend/scripts/upgrade_db.py --owner-email your@gmail.com")
        print("  Save this password in your password manager now — it is not recoverable.\n")
    finally:
        await session.close()
        await dispose_engine()


if __name__ == "__main__":
    run(main())     # not asyncio.run — see run() in app/db/database.py
