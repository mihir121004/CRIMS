# CRIMS — Citizen Reporting & Investigation Management System

A Django web application for the intake, triage and investigation of citizen crime
reports. Citizens file and track complaints; law-enforcement staff work a departmental
queue, attach evidence, manage suspects and witnesses, and file FIRs.

- **Stack:** Django 5.2.7 · MySQL/TiDB · Bootstrap 5.3.7 · scikit-learn · Vercel
- **Tests:** 147 passing

### Live deployment

**https://crims-eta.vercel.app**

The public pages (`/`, `/login/`, `/register/`) and `/health/` work. **Registration
does not** — the mail transport has no valid credentials, so the verification email
never leaves the server and no account can be completed. See
[Known blockers](#known-blockers) for the rest, including why the app is not yet ready
for real users.

---

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Environment variables](#environment-variables)
- [Running tests](#running-tests)
- [Deploying](#deploying)
- [Database migrations](#database-migrations) ← **read before deploying**
- [Roles](#roles)
- [Project layout](#project-layout)
- [Architecture notes](#architecture-notes)
- [Known blockers](#known-blockers)
- [Security notes](#security-notes)

---

## Features

| Area | What it does |
|---|---|
| **Accounts** | Registration, email verification via OTP, login, password reset, role-based approval of officer accounts |
| **Complaints** | Public reporting with tracking IDs, AI category/priority triage, status transitions, citizen and officer dashboards |
| **Evidence** | File uploads with type/size validation and randomised paths, chain-of-custody transfers, uploader recorded |
| **Suspects / Witnesses** | Records with wanted status, witness-protection flag, photo upload |
| **Investigations** | Officer assignment, per-case timelines, notes restricted to the assigned officer |
| **Reports** | Activity audit trail, FIR PDF generation |
| **Analytics** | Crime map, dashboards, category distribution |
| **Notifications** | Per-user alerts, unread counts in the sidebar |
| **Messaging** | Per-complaint comment threads between citizens and staff |

---

## Quick start

Requires Python 3.12+ and a reachable MySQL-compatible database.

```bash
python -m venv env
source env/bin/activate

pip install -r requirements.txt

cp .env.example .env        # then edit it — see next section
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

If your database is TiDB Cloud, `crims/settings.py` automatically enables TLS when the
host contains `tidbcloud`. For any other host over the network, add `ssl` to the
`DATABASE_URL` query string (e.g. `?ssl_mode=REQUIRED`).

---

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `SECRET_KEY` | **yes** | Django signing key. The app **refuses to boot** without it — there is no committed fallback. |
| `DATABASE_URL` | **yes** | `mysql://user:pass@host:port/dbname`. Alternative: `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`. |
| `DEBUG` | no | `False` in production. |
| `ALLOWED_HOSTS` | production | Comma-separated hostnames. |
| `CSRF_TRUSTED_ORIGINS` | production | e.g. `https://your-app.vercel.app`. |
| `EMAIL_VERIFICATION_REQUIRED` | no | Defaults to `true`. Forces OTP verification before login. |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | mail | SMTP credentials. Use a Google **app password**. |
| `EMAIL_BACKEND` | no | Explicit transport, e.g. `django.core.mail.backends.smtp.EmailBackend`. Overrides auto-detection. |
| `GMAIL_OAUTH_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GMAIL_REFRESH_TOKEN` | mail | Alternative XOAUTH2 transport (`accounts.email_backend.GmailOAuthBackend`). |
| `MEDIA_STORAGE` | production | Django `STORAGES` backend key for uploads, e.g. a `storages.backends.s3.S3Storage` backend. |
| `CRON_SECRET` | deploy | Bearer token for `POST /internal/migrate/`. Without it that route refuses all requests. |
| `LOG_LEVEL` | no | Defaults to `INFO`. |

`EMAIL_BACKEND` is resolved by `_resolve_email_backend()`: an explicit value wins,
otherwise the transport is inferred from whichever credentials are present. This exists
because Vercel secrets cannot be read back — deleting one to force a different transport
is a one-way door, so name the transport instead.

---

## Running tests

```bash
python manage.py test
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
```

Notable test modules:

| File | Covers |
|---|---|
| `crims/test_authorization_matrix.py` | Every URL × every role, and fails if a URL is added without a permission row |
| `accounts/test_auth_flows.py` | Registration → verification → login, mail outages, the migrate route's access control |
| `crims/test_schema_ops.py` | The TiDB foreign-key split |
| `crims/test_template_comments.py` | Lints templates so source comments can't be rendered to users |
| `crims/test_email_backend_selection.py` | Mail transport resolution |

---

## Deploying

The project deploys to Vercel using the `builds` array in `vercel.json`, which routes
every request through the `crims/wsgi.py` WSGI handler.

```bash
vercel --prod
```

Static assets are pre-collected and committed under `staticfiles/`. `.vercelignore`
keeps `.env*`, `env/`, `media/` and `scripts/` out of the function bundle.

> **Deploying does not migrate the database.** See the next section.

---

## Database migrations

**Vercel has no release phase and no shell, so a deploy does not update the schema.**
A deploy that adds a migration leaves production code expecting columns that do not
exist, and the first query touching that table raises `OperationalError`. This is not
hypothetical: it is exactly how `POST /login/` started returning HTTP 500 with
`Unknown column 'accounts_user.otp_salt'`.

### Checking for drift

```bash
SECRET=$(cat .env.cron-secret)
curl -s -H "Authorization: Bearer $SECRET" https://your-app.vercel.app/internal/migrate/
# {"status": "up-to-date", "applied": []}
```

### Applying migrations

```bash
curl -s -X POST -H "Authorization: Bearer $SECRET" \
  https://your-app.vercel.app/internal/migrate/
```

`GET` is read-only; `POST` applies. Each migration runs in its own transaction, so an
interrupted run can simply be repeated.

### The route's access control

`GET /internal/migrate/` exists because the production `DATABASE_URL` is a Vercel
*sensitive* variable — write-only, and unreadable via `vercel env pull` — so the
migration cannot be run from a workstation. Letting Vercel run it inside its own
environment is the only option.

Guards, all of which must pass:

- `CRON_SECRET` must be configured, otherwise the route refuses everything (fails
  closed — it never falls open).
- `Authorization: Bearer <CRON_SECRET>`, compared with `secrets.compare_digest`.
- Only `GET` and `POST` do anything; every other verb is a `405`.
- The response never echoes the token, the connection string, or the exception text.
  Tracebacks go to the `crims.errors` log, which is the only place they are safe.

`csrf_exempt` is deliberate: this route's authority is an explicit bearer header, not an
ambient cookie, so there is nothing for CSRF to protect — a browser will not attach an
`Authorization` header on its own. Without the exemption the documented `curl` would
fail with a 403.

### TiDB: adding a foreign-key column

Production runs **TiDB**, which rejects the single-statement form Django's MySQL backend
emits when adding an FK column — a constraint cannot reference a column introduced by
the same statement:

```
ALTER TABLE evidence ADD COLUMN uploaded_by_id bigint NULL,
  ADD CONSTRAINT ... FOREIGN KEY (uploaded_by_id) REFERENCES accounts_user (id)

(1072, "Key column 'uploaded_by_id' doesn't exist in table")
```

Local MySQL accepts this, so no local test can catch it.

`crims/schema_ops.py` provides `SplitForeignKeyAddField`, which forces Django down its
deferred-constraint path and then waits for the new column to become visible in
`information_schema`, because TiDB publishes DDL asynchronously. **Any future migration
that adds a foreign key to a newly-added column must use it:**

```python
from crims.schema_ops import SplitForeignKeyAddField

operations = [
    SplitForeignKeyAddField(
        model_name='widget',
        name='owner',
        field=models.ForeignKey(settings.AUTH_USER_MODEL, ...),
    ),
]
```

### No pre-migration backup

While `DATABASE_URL` is a Vercel secret, `mysqldump` against production is not possible
from a workstation. Take a provider-level snapshot before large schema changes.

---

## Roles

| Role | Can |
|---|---|
| `citizen` | Register, file complaints, track their own, upload evidence to their own cases, comment on their cases |
| `officer` | Work the departmental queue (assigned cases), attach evidence, manage suspects/witnesses/investigations, add case notes, view analytics |
| `admin` | Everything officers can, plus approve/reject officer registrations and the departmental analytics |

Sidebar links are gated to match view permissions, so a citizen never sees a link that
would return a 403.

---

## Project layout

```
crims/                 settings, URLs, error handlers, schema_ops
accounts/              auth, OTP, roles, the migrate route
complaints/            core case model and triage
evidence/              uploads and chain of custody
suspects/ witnesses/   persons of interest
investigations/        officer assignment and case timelines
reports/               activity log and FIR PDFs
notifications/         per-user alerts
communications/        per-complaint threads
analytics_dashboard/   dashboards and crime map
ai_engine/             TF-IDF classifier for category + priority triage
templates/             45 templates, including components/sidebar.html
static/css/            layout layer (crims.css, responsive.css, style.css)
static/js/             dashboard + responsive behaviour
staticfiles/           collectstatic output, committed for Vercel
scripts/               developer tools (not deployed)
```

---

## Architecture notes

**The `ai_engine` is a local classifier, not a language model.** It is a TF-IDF vectoriser
feeding a `MultinomialNB` classifier, trained on a small in-repo sample set. It cannot
reliably separate the classes, so `predict_confidence()` returns `0` below a usable
threshold and the UI shows "unclassified" rather than a fabricated percentage. Treat its
output as a triage hint, not a classification.

**OTPs** are generated with `secrets` (OS CSPRNG, not `random`), bound to a purpose
(`verify` vs `reset`) and stored salted and hashed, so a database leak does not yield
usable codes. Verification is scoped to the session, never matched against all users.

**Filenames on upload** are randomised per complaint rather than reusing the client's
original name, and are validated by extension allow-list and size cap.

**Passwords** use PBKDF2 with Django's four default validators.

---

## Known blockers

These are real and unresolved. The application is **not** suitable for real users until
they are closed.

1. **Verification email does not work.** Production has no working mail transport. The
   Gmail OAuth refresh token returns `invalid_grant: Token has been expired or revoked`,
   and the stored SMTP app password is rejected (`535 5.7.8`). Registration therefore
   fails with "We could not send the verification email", the account is rolled back, and
   `/verify-email/` has no code to verify. The backend is already switched to SMTP —
   set `EMAIL_HOST_PASSWORD` to a valid Google app password to fix it, or renew the OAuth
   token with `python scripts/renew_gmail_token.py`.

2. **`/media/` returns 404.** Uploads are validated and safely named but have nowhere to
   land: the Vercel filesystem is ephemeral and read-only. Evidence files, suspect photos
   and ID documents cannot be stored or retrieved. Set `MEDIA_STORAGE` to an
   S3-compatible backend and supply credentials.

3. **`SECRET_KEY` must be rotated.** The value committed in the initial commit
   (`2a00dbe`) is in this repository's history. Anyone with repository access could forge
   session cookies and password-reset tokens signed with it.

4. **No external uptime monitoring.** `/health/` exists and reports database reachability
   without leaking configuration, but nothing polls it and there is no 5xx alerting.

---

## Security notes

- `SECURE_SSL_REDIRECT`, HSTS (1 year, subdomains, preload), secure/httponly/samesite
  cookies, `X-Frame-Options: DENY`, `nosniff`, and a same-origin referrer policy are all
  active under `DEBUG=False`.
- `crims/test_authorization_matrix.py` fails if a URL is added without an explicit
  permission row, so new views cannot quietly ship unprotected.
- Self-registration cannot create an administrator: the role is taken from a
  whitelisted `ChoiceField` and re-validated server-side.
- 403/404/500 pages render no diagnostics and no request internals.
- `SECRET_KEY` has no fallback — the app refuses to start without it rather than running
  on a public default.

### Before making this repository public

The `SECRET_KEY` in commit `2a00dbe` is readable by anyone with repository access. Rotate
the production key, or rewrite that commit's history, before changing visibility.
