import os
import sqlite3

# Get absolute path to the database file inside your project folder
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # directory of your current script (e.g., app.py)
DB_PATH = os.path.join(BASE_DIR, 'data', 'database.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            cleared INTEGER DEFAULT 0,
            name TEXT,
            department TEXT
        )
    ''')
    # create other tables as needed here
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")
