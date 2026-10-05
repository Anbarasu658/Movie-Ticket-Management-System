import os

from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row


load_dotenv()


def get_db_connection():
    """Create and return a PostgreSQL database connection."""

    database_url = os.getenv("DATABASE_URL")

    if database_url:
        return psycopg.connect(
            database_url,
            row_factory=dict_row
        )

    required = {
        "DB_HOST": os.getenv("DB_HOST"),
        "DB_PORT": os.getenv("DB_PORT", "5432"),
        "DB_NAME": os.getenv("DB_NAME"),
        "DB_USER": os.getenv("DB_USER"),
        "DB_PASSWORD": os.getenv("DB_PASSWORD"),
    }

    missing = [
        key
        for key, value in required.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "PostgreSQL configuration is missing: "
            + ", ".join(missing)
        )

    return psycopg.connect(
        host=required["DB_HOST"],
        port=int(required["DB_PORT"]),
        dbname=required["DB_NAME"],
        user=required["DB_USER"],
        password=required["DB_PASSWORD"],
        row_factory=dict_row
    )
