"""
High School Management System API

A FastAPI application for viewing and signing up for extracurricular activities
at Mergington High School.
"""

from contextlib import asynccontextmanager, contextmanager
import hashlib
import hmac
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import AsyncGenerator, Callable, Generator, Literal, TypedDict

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)
current_dir = Path(__file__).parent
DATABASE_PATH = Path(
    os.environ.get("DATABASE_PATH", str(current_dir / "activities.sqlite"))
)
PASSWORD_HASH_ITERATIONS = 600_000
SESSION_LIFETIME_SECONDS = 8 * 60 * 60
SESSION_COOKIE_NAME = "mergington_session"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
Role = Literal["student", "teacher", "club_advisor"]


def read_bool_setting(name: str, default: str) -> bool:
    value = os.environ.get(name, default).lower()
    if value not in {"true", "false"}:
        raise RuntimeError(f"{name} must be set to 'true' or 'false'")
    return value == "true"


SESSION_COOKIE_SECURE = read_bool_setting("SESSION_COOKIE_SECURE", "false")


class User(TypedDict):
    email: str
    role: Role


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class NewUser(Credentials):
    password: str = Field(min_length=12, max_length=128)
    role: Role


def normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if len(normalized) > 254 or not EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("A valid email address is required")
    return normalized


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    return f"{salt.hex()}${password_hash.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    salt_hex, expected_hash = password_hash.split("$", maxsplit=1)
    actual_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return hmac.compare_digest(actual_hash, expected_hash)


@contextmanager
def database_connection() -> Generator[sqlite3.Connection, None, None]:
    connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


activities = {
    "Chess Club": {
        "description": "Learn strategies and compete in chess tournaments",
        "schedule": "Fridays, 3:30 PM - 5:00 PM",
        "max_participants": 12,
        "participants": ["michael@mergington.edu", "daniel@mergington.edu"],
    },
    "Programming Class": {
        "description": "Learn programming fundamentals and build software projects",
        "schedule": "Tuesdays and Thursdays, 3:30 PM - 4:30 PM",
        "max_participants": 20,
        "participants": ["emma@mergington.edu", "sophia@mergington.edu"],
    },
    "Gym Class": {
        "description": "Physical education and sports activities",
        "schedule": "Mondays, Wednesdays, Fridays, 2:00 PM - 3:00 PM",
        "max_participants": 30,
        "participants": ["john@mergington.edu", "olivia@mergington.edu"],
    },
    "Soccer Team": {
        "description": "Join the school soccer team and compete in matches",
        "schedule": "Tuesdays and Thursdays, 4:00 PM - 5:30 PM",
        "max_participants": 22,
        "participants": ["liam@mergington.edu", "noah@mergington.edu"],
    },
    "Basketball Team": {
        "description": "Practice and play basketball with the school team",
        "schedule": "Wednesdays and Fridays, 3:30 PM - 5:00 PM",
        "max_participants": 15,
        "participants": ["ava@mergington.edu", "mia@mergington.edu"],
    },
    "Art Club": {
        "description": "Explore your creativity through painting and drawing",
        "schedule": "Thursdays, 3:30 PM - 5:00 PM",
        "max_participants": 15,
        "participants": ["amelia@mergington.edu", "harper@mergington.edu"],
    },
    "Drama Club": {
        "description": "Act, direct, and produce plays and performances",
        "schedule": "Mondays and Wednesdays, 4:00 PM - 5:30 PM",
        "max_participants": 20,
        "participants": ["ella@mergington.edu", "scarlett@mergington.edu"],
    },
    "Math Club": {
        "description": "Solve challenging problems and participate in math competitions",
        "schedule": "Tuesdays, 3:30 PM - 4:30 PM",
        "max_participants": 10,
        "participants": ["james@mergington.edu", "benjamin@mergington.edu"],
    },
    "Debate Team": {
        "description": "Develop public speaking and argumentation skills",
        "schedule": "Fridays, 4:00 PM - 5:30 PM",
        "max_participants": 12,
        "participants": ["charlotte@mergington.edu", "henry@mergington.edu"],
    },
}


def create_user_record(email: str, password: str, role: Role) -> User:
    with database_connection() as connection:
        connection.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)",
            (email, hash_password(password), role),
        )
    return {"email": email, "role": role}


def initialize_database() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with database_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS activities (
                name TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                schedule TEXT NOT NULL,
                max_participants INTEGER NOT NULL CHECK (max_participants >= 0)
            );
            CREATE TABLE IF NOT EXISTS participants (
                activity_name TEXT NOT NULL REFERENCES activities(name) ON DELETE CASCADE,
                email TEXT NOT NULL,
                PRIMARY KEY (activity_name, email)
            );
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('student', 'teacher', 'club_advisor'))
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_email TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            """
        )
        for name, details in activities.items():
            connection.execute(
                """
                INSERT OR IGNORE INTO activities
                    (name, description, schedule, max_participants)
                VALUES (?, ?, ?, ?)
                """,
                (
                    name,
                    details["description"],
                    details["schedule"],
                    details["max_participants"],
                ),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO participants (activity_name, email) VALUES (?, ?)",
                ((name, email) for email in details["participants"]),
            )

    teacher_email = os.environ.get("INITIAL_TEACHER_EMAIL")
    teacher_password = os.environ.get("INITIAL_TEACHER_PASSWORD")
    if bool(teacher_email) != bool(teacher_password):
        raise RuntimeError(
            "Set both INITIAL_TEACHER_EMAIL and INITIAL_TEACHER_PASSWORD"
        )
    if not teacher_email:
        logger.warning(
            "No initial teacher configured; set INITIAL_TEACHER_EMAIL and "
            "INITIAL_TEACHER_PASSWORD to enable authenticated actions."
        )
        return
    if len(teacher_password) < 12:
        raise RuntimeError("INITIAL_TEACHER_PASSWORD must be at least 12 characters")

    normalized_email = normalize_email(teacher_email)
    with database_connection() as connection:
        existing_user = connection.execute(
            "SELECT role FROM users WHERE email = ?", (normalized_email,)
        ).fetchone()
        if existing_user is None:
            connection.execute(
                "INSERT INTO users (email, password_hash, role) VALUES (?, ?, 'teacher')",
                (normalized_email, hash_password(teacher_password)),
            )
        elif existing_user["role"] != "teacher":
            raise RuntimeError(
                "INITIAL_TEACHER_EMAIL belongs to an account that is not a teacher"
            )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    initialize_database()
    yield


app = FastAPI(
    title="Mergington High School API",
    description="API for viewing and signing up for extracurricular activities",
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=os.path.join(Path(__file__).parent, "static")),
    name="static",
)


def get_session_user(request: Request) -> User | None:
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return None
    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
    now = int(time.time())
    with database_connection() as connection:
        session = connection.execute(
            """
            SELECT users.email, users.role, sessions.expires_at
            FROM sessions
            JOIN users ON users.email = sessions.user_email
            WHERE sessions.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if session is None:
            return None
        if session["expires_at"] <= now:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (token_hash,)
            )
            return None
    return {"email": session["email"], "role": session["role"]}


def require_authenticated_user(request: Request) -> User:
    user = get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_role(*roles: Role) -> Callable[[Request], User]:
    def role_dependency(request: Request) -> User:
        user = require_authenticated_user(request)
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return role_dependency


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/static/index.html")


@app.get("/auth/me")
def get_current_user(request: Request) -> dict[str, str | bool]:
    user = get_session_user(request)
    if user is None:
        return {"authenticated": False}
    return {"authenticated": True, **user}


@app.post("/auth/login")
def login(credentials: Credentials, response: Response) -> User:
    email = credentials.email.strip().casefold()
    with database_connection() as connection:
        user_record = connection.execute(
            "SELECT email, password_hash, role FROM users WHERE email = ?", (email,)
        ).fetchone()
    if user_record is None or not verify_password(
        credentials.password, user_record["password_hash"]
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    session_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
    with database_connection() as connection:
        connection.execute(
            "INSERT INTO sessions (token_hash, user_email, expires_at) VALUES (?, ?, ?)",
            (
                token_hash,
                user_record["email"],
                int(time.time()) + SESSION_LIFETIME_SECONDS,
            ),
        )
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=SESSION_LIFETIME_SECONDS,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return {"email": user_record["email"], "role": user_record["role"]}


@app.post("/auth/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        token_hash = hashlib.sha256(session_token.encode("utf-8")).hexdigest()
        with database_connection() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (token_hash,)
            )
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return {"message": "Logged out"}


@app.post("/auth/users", status_code=201)
def create_user(
    new_user: NewUser,
    _: User = Depends(require_role("teacher")),
) -> User:
    try:
        email = normalize_email(new_user.email)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        return create_user_record(email, new_user.password, new_user.role)
    except sqlite3.IntegrityError as error:
        if "users.email" in str(error):
            raise HTTPException(status_code=409, detail="An account already exists") from error
        raise


@app.get("/activities")
def get_activities() -> dict[str, dict[str, str | int | list[str]]]:
    with database_connection() as connection:
        activity_rows = connection.execute(
            "SELECT name, description, schedule, max_participants FROM activities"
        ).fetchall()
        participant_rows = connection.execute(
            "SELECT activity_name, email FROM participants ORDER BY email"
        ).fetchall()
    participants_by_activity: dict[str, list[str]] = {}
    for participant in participant_rows:
        participants_by_activity.setdefault(participant["activity_name"], []).append(
            participant["email"]
        )
    return {
        activity["name"]: {
            "description": activity["description"],
            "schedule": activity["schedule"],
            "max_participants": activity["max_participants"],
            "participants": participants_by_activity.get(activity["name"], []),
        }
        for activity in activity_rows
    }


@app.post("/activities/{activity_name}/signup")
def signup_for_activity(
    activity_name: str,
    email: str | None = None,
    user: User = Depends(require_authenticated_user),
) -> dict[str, str]:
    if user["role"] == "teacher":
        if email is None:
            raise HTTPException(
                status_code=422, detail="Teachers must provide a student email"
            )
        try:
            participant_email = normalize_email(email)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    else:
        participant_email = user["email"]
        if email is not None and email.strip().casefold() != participant_email:
            raise HTTPException(
                status_code=403, detail="You can only manage your own signup"
            )

    with database_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        activity = connection.execute(
            "SELECT max_participants FROM activities WHERE name = ?", (activity_name,)
        ).fetchone()
        if activity is None:
            raise HTTPException(status_code=404, detail="Activity not found")
        existing = connection.execute(
            "SELECT 1 FROM participants WHERE activity_name = ? AND email = ?",
            (activity_name, participant_email),
        ).fetchone()
        if existing is not None:
            raise HTTPException(status_code=400, detail="Student is already signed up")
        participant_count = connection.execute(
            "SELECT COUNT(*) FROM participants WHERE activity_name = ?",
            (activity_name,),
        ).fetchone()[0]
        if participant_count >= activity["max_participants"]:
            raise HTTPException(status_code=400, detail="Activity is full")
        connection.execute(
            "INSERT INTO participants (activity_name, email) VALUES (?, ?)",
            (activity_name, participant_email),
        )
    return {"message": f"Signed up {participant_email} for {activity_name}"}


@app.delete("/activities/{activity_name}/unregister")
def unregister_from_activity(
    activity_name: str,
    email: str | None = None,
    user: User = Depends(require_authenticated_user),
) -> dict[str, str]:
    if user["role"] == "teacher":
        if email is None:
            raise HTTPException(
                status_code=422, detail="Teachers must provide a student email"
            )
        try:
            participant_email = normalize_email(email)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    else:
        participant_email = user["email"]
        if email is not None and email.strip().casefold() != participant_email:
            raise HTTPException(
                status_code=403, detail="You can only manage your own signup"
            )

    with database_connection() as connection:
        activity = connection.execute(
            "SELECT 1 FROM activities WHERE name = ?", (activity_name,)
        ).fetchone()
        if activity is None:
            raise HTTPException(status_code=404, detail="Activity not found")
        cursor = connection.execute(
            "DELETE FROM participants WHERE activity_name = ? AND email = ?",
            (activity_name, participant_email),
        )
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=400,
                detail="Student is not signed up for this activity",
            )
    return {"message": f"Unregistered {participant_email} from {activity_name}"}
