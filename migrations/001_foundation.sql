CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL
);
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at INTEGER NOT NULL
);
CREATE TABLE households (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 100),
    owner_id INTEGER NOT NULL REFERENCES users(id),
    FOREIGN KEY (id, owner_id) REFERENCES memberships(household_id, user_id)
        DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE memberships (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    household_id INTEGER NOT NULL REFERENCES households(id),
    UNIQUE(household_id, user_id)
);
CREATE TABLE invitations (
    id INTEGER PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households(id),
    code_hash TEXT NOT NULL UNIQUE,
    expires_at INTEGER NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1)),
    used_by INTEGER REFERENCES users(id)
);
CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY,
    household_id INTEGER NOT NULL REFERENCES households(id),
    actor_id INTEGER NOT NULL REFERENCES users(id),
    action TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'success',
    reason TEXT NOT NULL,
    target_id INTEGER,
    occurred_at INTEGER NOT NULL
);
CREATE TABLE invite_attempts (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    started INTEGER NOT NULL,
    failures INTEGER NOT NULL
);
