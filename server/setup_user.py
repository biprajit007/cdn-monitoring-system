#!/usr/bin/env python3
"""Setup script to create default admin user in the database."""

import sqlite3
import sys
import os
from passlib.context import CryptContext

DB = '/app/data/metrics.db'
pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')

def setup_user(username: str, password: str):
    """Create or update a user account."""
    os.makedirs('/app/data', exist_ok=True)

    conn = sqlite3.connect(DB)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        hashed_password TEXT NOT NULL,
        created_at INTEGER NOT NULL
    )
    """)

    hashed = pwd_context.hash(password)
    import time
    try:
        conn.execute(
            'INSERT INTO users(username, hashed_password, created_at) VALUES (?, ?, ?)',
            (username, hashed, int(time.time()))
        )
        conn.commit()
        print(f'✓ User created: {username}')
    except sqlite3.IntegrityError:
        conn.execute(
            'UPDATE users SET hashed_password=? WHERE username=?',
            (hashed, username)
        )
        conn.commit()
        print(f'✓ User updated: {username}')
    finally:
        conn.close()

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('Usage: python setup_user.py <username> <password>')
        sys.exit(1)

    setup_user(sys.argv[1], sys.argv[2])
