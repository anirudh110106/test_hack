import sqlite3
import os

BASE_DIR = os.path.dirname(__file__)
DB_NAME = os.path.join(BASE_DIR, "metadata.db")


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS images (
        image_id TEXT PRIMARY KEY,
        lat REAL,
        lon REAL,
        timestamp TEXT
    )
    """)

    conn.commit()
    conn.close()


def insert_image(data):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR REPLACE INTO images (image_id, lat, lon, timestamp)
    VALUES (?, ?, ?, ?)
    """, (data["image_id"], data["lat"], data["lon"], data["timestamp"]))

    conn.commit()
    conn.close()


def fetch_all():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM images")
    rows = cursor.fetchall()

    conn.close()
    return rows