import os
from http.cookies import SimpleCookie
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.responses import Response
from starlette.requests import Request

from src import app as app_module


class AuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path_patcher = patch.object(
            app_module,
            "DATABASE_PATH",
            Path(self.temporary_directory.name) / "test.sqlite",
        )
        self.database_path_patcher.start()
        self.environment_patcher = patch.dict(
            os.environ,
            {
                "INITIAL_TEACHER_EMAIL": "teacher@mergington.edu",
                "INITIAL_TEACHER_PASSWORD": "a-secure-teacher-password",
            },
        )
        self.environment_patcher.start()
        app_module.initialize_database()

    def tearDown(self) -> None:
        self.environment_patcher.stop()
        self.database_path_patcher.stop()
        self.temporary_directory.cleanup()

    def login_as(
        self, email: str, password: str
    ) -> tuple[dict[str, str], Request, Response]:
        response = Response()
        user = app_module.login(
            app_module.Credentials(email=email, password=password), response
        )
        cookies = SimpleCookie()
        cookies.load(response.headers["set-cookie"])
        session_cookie = cookies[app_module.SESSION_COOKIE_NAME].value
        request = Request(
            {
                "type": "http",
                "headers": [
                    (
                        b"cookie",
                        f"{app_module.SESSION_COOKIE_NAME}={session_cookie}".encode(),
                    )
                ],
            }
        )
        return user, request, response

    def test_teacher_bootstrap_and_login_use_hashed_passwords(self) -> None:
        user, request, response = self.login_as(
            "TEACHER@mergington.edu", "a-secure-teacher-password"
        )

        self.assertEqual(
            user, {"email": "teacher@mergington.edu", "role": "teacher"}
        )
        self.assertEqual(app_module.get_session_user(request), user)
        set_cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", set_cookie)
        self.assertIn("samesite=lax", set_cookie)
        with app_module.database_connection() as connection:
            stored_hash = connection.execute(
                "SELECT password_hash FROM users WHERE email = ?",
                ("teacher@mergington.edu",),
            ).fetchone()["password_hash"]
        self.assertNotEqual(stored_hash, "a-secure-teacher-password")
        self.assertTrue(
            app_module.verify_password("a-secure-teacher-password", stored_hash)
        )
        self.assertFalse(app_module.verify_password("wrong-password", stored_hash))

    def test_sessions_are_revoked_when_expired(self) -> None:
        _, request, _ = self.login_as(
            "teacher@mergington.edu", "a-secure-teacher-password"
        )
        token = request.cookies[app_module.SESSION_COOKIE_NAME]
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with app_module.database_connection() as connection:
            connection.execute(
                "UPDATE sessions SET expires_at = 0 WHERE token_hash = ?",
                (token_hash,),
            )

        self.assertIsNone(app_module.get_session_user(request))
        with app_module.database_connection() as connection:
            remaining_sessions = connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE token_hash = ?", (token_hash,)
            ).fetchone()[0]
        self.assertEqual(remaining_sessions, 0)

    def test_logout_revokes_the_session(self) -> None:
        _, request, _ = self.login_as(
            "teacher@mergington.edu", "a-secure-teacher-password"
        )

        response = Response()
        self.assertEqual(
            app_module.logout(request, response), {"message": "Logged out"}
        )
        self.assertIsNone(app_module.get_session_user(request))
        self.assertIn("max-age=0", response.headers["set-cookie"].lower())

    def test_students_can_only_manage_their_own_signup(self) -> None:
        student = app_module.create_user_record(
            "student@mergington.edu", "a-secure-student-password", "student"
        )
        _, request, _ = self.login_as(
            "student@mergington.edu", "a-secure-student-password"
        )

        self.assertEqual(app_module.get_session_user(request), student)
        app_module.signup_for_activity("Chess Club", None, student)
        with self.assertRaises(HTTPException) as denied:
            app_module.signup_for_activity(
                "Chess Club", "another-student@mergington.edu", student
            )
        self.assertEqual(denied.exception.status_code, 403)
        with self.assertRaises(HTTPException) as role_denied:
            app_module.require_role("teacher")(request)
        self.assertEqual(role_denied.exception.status_code, 403)

    def test_teachers_can_create_users_and_manage_other_signups(self) -> None:
        teacher, _, _ = self.login_as(
            "teacher@mergington.edu", "a-secure-teacher-password"
        )
        created_user = app_module.create_user(
            app_module.NewUser(
                email="student@mergington.edu",
                password="a-secure-student-password",
                role="student",
            ),
            teacher,
        )

        self.assertEqual(created_user["role"], "student")
        result = app_module.signup_for_activity(
            "Chess Club", "student@mergington.edu", teacher
        )
        self.assertEqual(
            result["message"], "Signed up student@mergington.edu for Chess Club"
        )

    def test_activity_signups_survive_database_reinitialization(self) -> None:
        student = app_module.create_user_record(
            "student@mergington.edu", "a-secure-student-password", "student"
        )
        app_module.signup_for_activity("Chess Club", None, student)

        app_module.initialize_database()

        self.assertIn(
            "student@mergington.edu",
            app_module.get_activities()["Chess Club"]["participants"],
        )

    def test_login_rejects_unknown_users(self) -> None:
        with self.assertRaises(HTTPException) as denied:
            app_module.login(
                app_module.Credentials(
                    email="unknown@mergington.edu", password="not-a-password"
                ),
                Response(),
            )
        self.assertEqual(denied.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
