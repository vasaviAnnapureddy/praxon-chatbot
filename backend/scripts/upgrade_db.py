"""
Brings a database up to date with the login + client-portal tables.

    python backend/scripts/upgrade_db.py
    python backend/scripts/upgrade_db.py --owner-email you@gmail.com

What it does, in order — and it is safe to run as many times as you like:
  1. creates any NEW tables (users, projects, project_updates, project_members,
     access_requests) and adds the temporary-password columns to `users`.
     Existing data is never touched.
  2. copies each old `admins` login into `users` as the OWNER, same username,
     same password. Skipped if already copied.
  3. with --owner-email: puts that email on the owner account, so the owner
     can also use "Continue with Google".

Run it once on dev, and once on production before deploying.

  Q: Why a script, not automatically when the app starts?
  A: Same rule as ingest.py: a restart must never be able to change the
     database's structure. You change it, on purpose, by running this.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text  # noqa: E402

from app.core.logging import setup_logging  # noqa: E402
from app.db import crud  # noqa: E402
from app.db.database import dispose_engine, get_engine, run, session_scope  # noqa: E402
from app.db.models import Admin, Base, User  # noqa: E402

setup_logging()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Add login + portal tables, migrate the admin")
    parser.add_argument("--owner-email", default="", help="email for the owner's Google sign-in")
    args = parser.parse_args()

    print("\n  Upgrading the database")
    try:
        # 1. New tables only. create_all skips tables that already exist.
        async with get_engine().begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
            #   Q: create_all made the new tables. Why these two lines as well?
            #   A: create_all never changes a table that already exists, and
            #      `users` already does. IF NOT EXISTS makes re-running harmless.
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE"))
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS temp_password_expires_at TIMESTAMPTZ"))
        print("  [ OK ] tables ready: users, projects, project_updates, project_members, access_requests")

        session = await session_scope()
        try:
            # 2. Old admin logins -> owners.
            admins = (await session.scalars(select(Admin))).all()
            copied = 0
            for admin in admins:
                if await crud.find_user_for_login(session, admin.username):
                    continue                                   # already copied
                await crud.create_user(
                    session, role="owner", username=admin.username,
                    name=admin.username, password_hash=admin.password_hash,
                )
                copied += 1
            print(f"  [ OK ] owner logins copied: {copied} new, {len(admins) - copied} already there")

            # 3. Owner email for Google sign-in.
            if args.owner_email:
                email = args.owner_email.strip().lower()
                clash = await crud.get_user_by_email(session, email)
                owner = await session.scalar(
                    select(User).where(User.role == "owner").order_by(User.id)
                )
                if owner is None:
                    print("  [FAIL] no owner account yet — run create_admin.py first")
                elif clash is not None and clash.id != owner.id:
                    print(f"  [FAIL] {email} already belongs to another account")
                else:
                    owner.email = email
                    await session.commit()
                    print(f"  [ OK ] owner '{owner.username}' can now also sign in with Google as {email}")

            owners = await crud.list_users(session, ["owner"])
            print("\n  Owners now:", ", ".join(o.username or o.email for o in owners) or "(none)")
        finally:
            await session.close()
    finally:
        await dispose_engine()
    print()


if __name__ == "__main__":
    run(main())
