"""Serving layer for the store migration.

Turns the derived parquet into the Postgres serving store (Supabase). `build_db.py`
is the loader — the new publish seam that replaces the hand-symlink step.
"""
