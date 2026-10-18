# Mergington High School Activities API

A FastAPI application that lets students view extracurricular activities and use
authenticated accounts to manage signups.

## Features

- View all available extracurricular activities
- SQLite persistence for activities, participants, users, and sessions
- Student and club-advisor accounts can manage only their own signups
- Teachers can manage student signups and create accounts with assigned roles
- Passwords are stored as salted PBKDF2 hashes; sessions use HttpOnly cookies

## Getting Started

1. Install the dependencies:

   ```
   pip install -r requirements.txt
   ```

2. Configure the first teacher account before starting the app. Set both
   `INITIAL_TEACHER_EMAIL` and `INITIAL_TEACHER_PASSWORD`; the password must be
   at least 12 characters. For VS Code, put these values in the ignored
   workspace `.env` file so the launch configuration can load them. In a
   terminal, export them before starting the app. The teacher is created on the
   first startup, and restarting with the same email does not reset its
   password.

3. Start the application from the repository root:

   ```
   uvicorn src.app:app --reload
   ```

4. Open http://localhost:8000. For production, set
   `SESSION_COOKIE_SECURE=true` and serve the application over HTTPS. The
   default SQLite file is `src/activities.sqlite`; set `DATABASE_PATH` to
   choose another location.

## API Endpoints

| Method | Endpoint                                 | Access                 | Description                                      |
| ------ | ---------------------------------------- | ---------------------- | ------------------------------------------------ |
| GET    | `/activities`                            | Public                 | List activities and current participants        |
| GET    | `/auth/me`                               | Public                 | Return the current login state                  |
| POST   | `/auth/login`                            | Public                 | Log in with an email and password               |
| POST   | `/auth/logout`                           | Public                 | Invalidate the current session                  |
| POST   | `/auth/users`                            | Teacher                | Create a student, teacher, or club-advisor user |
| POST   | `/activities/{activity_name}/signup`     | Student, advisor, teacher | Sign up the current user; teachers pass `email` |
| DELETE | `/activities/{activity_name}/unregister` | Student, advisor, teacher | Unregister the current user; teachers pass `email` |

Login and user-creation requests use JSON. Example:

```json
{
  "email": "student@mergington.edu",
  "password": "a-password-at-least-12-characters",
  "role": "student"
}
```

Do not enable public self-registration. A teacher creates accounts through
`POST /auth/users` or the teacher-only account form in the web UI.

## Data Model

Activity and participant data is initialized from the built-in seed data on the
first run and then stored in SQLite. User passwords are salted and hashed;
only a hash of each random session token is stored in the database. Sessions
expire after eight hours.
