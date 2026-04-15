import duckdb
import os
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "digest.db")


def get_connection():
    return duckdb.connect(DB_PATH)


def init_db():
    with get_connection() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS feeds (
                id INTEGER PRIMARY KEY,
                url TEXT UNIQUE NOT NULL,
                title TEXT,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
        """)
        con.execute("""
            CREATE SEQUENCE IF NOT EXISTS feeds_id_seq START 1
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY,
                feed_id INTEGER NOT NULL REFERENCES feeds(id),
                guid TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                published_at TIMESTAMP,
                link TEXT,
                fetched_at TIMESTAMP DEFAULT current_timestamp
            )
        """)
        con.execute("""
            CREATE SEQUENCE IF NOT EXISTS episodes_id_seq START 1
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS interests (
                id INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT current_timestamp
            )
        """)
        con.execute("""
            CREATE SEQUENCE IF NOT EXISTS interests_id_seq START 1
        """)
