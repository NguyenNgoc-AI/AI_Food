CREATE TABLE login_attempts (
    bucket TEXT PRIMARY KEY NOT NULL,
    started INTEGER NOT NULL,
    attempts INTEGER NOT NULL CHECK(attempts >= 0)
);
CREATE INDEX login_attempts_started ON login_attempts(started);
