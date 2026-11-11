"""Test settings: real PostgreSQL 18. Connects as the owner so it can create the
test database; the tests themselves switch to goldvolt_app (see tests/conftest.py)."""
import os

os.environ["GOLDVOLT_DB_ROLE"] = "owner"

from .settings import *  # noqa: E402,F403

LOGGING = {"version": 1, "disable_existing_loggers": False}
