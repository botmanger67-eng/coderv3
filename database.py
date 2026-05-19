import sqlite3
from datetime import datetime
from enum import Enum
from contextlib import contextmanager
import json

class UserState(Enum):
    IDLE = "idle"
    WAITING_PROJECT_PROMPT = "waiting_project_prompt"
    WAITING_REPO_NAME = "waiting_repo_name"
    WAITING_CONFIRMATION = "waiting_confirmation"
    GENERATING_CODE = "generating_code"
    PUSHING_TO_GITHUB = "pushing_to_github"

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with self._get_connection() as conn:
            # users table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    state TEXT DEFAULT 'idle',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # conversation history
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    role TEXT,
                    content TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # project sessions (each generation attempt)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    project_prompt TEXT,
                    repo_name TEXT,
                    file_structure TEXT,
                    github_url TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # generated files content (large text)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS generated_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    file_path TEXT,
                    file_content TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # NEW: user project history (for "modify" feature)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_projects_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    session_id INTEGER,
                    project_name TEXT,
                    blueprint TEXT,
                    github_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES project_sessions(id)
                )
            """)

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get_or_create_user(self, user_id, username=None, first_name=None, last_name=None):
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
            conn.execute("INSERT INTO users (user_id, username, first_name, last_name) VALUES (?,?,?,?)",
                         (user_id, username, first_name, last_name))
            return {"user_id": user_id, "username": username}

    def update_user_state(self, user_id, state):
        with self._get_connection() as conn:
            conn.execute("UPDATE users SET state = ? WHERE user_id = ?", (state.value, user_id))

    def get_user_state(self, user_id):
        with self._get_connection() as conn:
            cur = conn.execute("SELECT state FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            return UserState(row["state"]) if row else UserState.IDLE

    def add_conversation_message(self, user_id, role, content):
        with self._get_connection() as conn:
            conn.execute("INSERT INTO conversation_history (user_id, role, content) VALUES (?,?,?)",
                         (user_id, role, content))

    def create_project_session(self, user_id, project_prompt=None):
        with self._get_connection() as conn:
            cur = conn.execute("INSERT INTO project_sessions (user_id, project_prompt) VALUES (?,?)",
                               (user_id, project_prompt))
            return cur.lastrowid

    def update_project_session(self, session_id, **kwargs):
        allowed = ["project_prompt", "repo_name", "file_structure", "github_url", "status"]
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join([f"{k} = ?" for k in updates])
        values = list(updates.values()) + [session_id]
        with self._get_connection() as conn:
            conn.execute(f"UPDATE project_sessions SET {set_clause} WHERE id = ?", values)

    def get_active_session(self, user_id):
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM project_sessions WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def save_generated_files(self, session_id, files):
        with self._get_connection() as conn:
            for path, content in files.items():
                conn.execute("INSERT INTO generated_files (session_id, file_path, file_content) VALUES (?,?,?)",
                             (session_id, path, content))

    def add_to_history(self, user_id, session_id, project_name, blueprint, github_url):
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO user_projects_history (user_id, session_id, project_name, blueprint, github_url) VALUES (?,?,?,?,?)",
                (user_id, session_id, project_name, json.dumps(blueprint), github_url)
            )

    def get_last_project_blueprint(self, user_id):
        """Return last completed project's blueprint dict for modification."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT blueprint FROM user_projects_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                (user_id,))
            row = cur.fetchone()
            if row and row["blueprint"]:
                return json.loads(row["blueprint"])
            return None

    def get_last_project_name(self, user_id):
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT project_name FROM user_projects_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                (user_id,))
            row = cur.fetchone()
            return row["project_name"] if row else None