# CRIMS — Deployment Checklist

Verified: 2026-10-01 against production deployment at `crims-eta.vercel.app`.

Status legend: `[x]` done · `[ ]` outstanding

---

## 1. Blocker — must complete before real users

- [ ] **Media storage.** `/media/` returns 404 in production. Evidence files,
      suspect photos and identity documents cannot be stored or retrieved.
      The filesystem on Vercel is ephemeral and read-only outside the build.
      Uploads are validated and paths are randomised, but they have nowhere
      to land.

      Provision a bucket and set the env vars below. The backend is already
      wired via `MEDIA_STORAGE` in `crims/settings.py`.

- [ ] **Verification email — BLOCKING (2026-10-01).** Production cannot send
      any email, so registration always fails with "We could not send the
      verification email" and the new account is rolled back. No OTP is ever
      issued, so `/verify-email/` has nothing to verify. Nobody can use the
      site until this is fixed.

      Original cause: `GMAIL_REFRESH_TOKEN` is dead. Google answers
      `invalid_grant: Token has been expired or revoked`, and since the client
      *is* recognised, the OAuth client itself is still valid. (The local
      `.env` copy is separately unusable — it returns `invalid_client`.)

      Two routes out, both needing browser/console work that cannot be done
      from the CLI because the credentials are write-only Vercel secrets:

      **A. Gmail app password over plain SMTP — chosen 2026-10-01.** Set
      `EMAIL_HOST_PASSWORD` in Vercel (production) to a Google *app
      password* from https://myaccount.google.com/apppasswords (requires
      2-Step Verification), and set:

      ```
      EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
      ```

      `EMAIL_BACKEND` is now honoured explicitly by `crims/settings.py`.
      This matters: the alternative way to reach the SMTP backend was to
      delete `GMAIL_OAUTH_CLIENT_ID`, and because Vercel secrets cannot be
      read back, deleting one is a one-way door. Naming the transport is
      reversible. The dead OAuth credentials can be left in place.

      **B. Renew the OAuth refresh token** with
      `python scripts/renew_gmail_token.py`. The OAuth client is type *Web
      application*, so the out-of-band redirect is rejected; it needs
      `https://crims-eta.vercel.app/oauth-callback` registered under
      Authorized redirect URIs first. If used, the consent screen's
      publishing status **must** be "In production", because refresh tokens
      issued while it reads "Testing" expire after 7 days.

      Confirm delivery afterwards by registering a throwaway account and
      looking for this line in `vercel logs`:

      ```
      verification email to ***@... accepted by the mail provider (purpose=verify)
      ```

      That line means Gmail accepted the message. It does **not** prove inbox
      delivery — spam filtering after acceptance is invisible to this code.

      **Do not delete the `GMAIL_*` variables** unless you intend route B to
      be unrecoverable.

## 2. Environment variables

Set in Vercel production:

| Variable | Status | Notes |
|---|---|---|
| `SECRET_KEY` | [x] set | The committed fallback is removed; the app refuses to boot without this. **Rotate it** — the old value is public in git history. |
| `DEBUG` | [x] set | `False` |
| `DATABASE_URL` | [x] set | |
| `ALLOWED_HOSTS` | [x] set | |
| `EMAIL_VERIFICATION_REQUIRED` | [x] set | `True` |
| `GMAIL_OAUTH_CLIENT_ID` / `GMAIL_CLIENT_SECRET` / `GMAIL_REFRESH_TOKEN` | [x] set | Token expired — see blocker 1 |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | [x] set | |
| `CSRF_TRUSTED_ORIGINS` | [x] added | `https://crims-eta.vercel.app` |
| `CRON_SECRET` | [x] set | Bearer token for `POST /internal/migrate/`. Stored as a Vercel *secret*, so it cannot be read back from the dashboard — the only copy is in `.env.cron-secret` (gitignored). **Move it to a password manager, then delete that file.** |
| `MEDIA_STORAGE` | [ ] **missing** | Required — see blocker 1 |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_STORAGE_BUCKET_NAME` | [ ] **missing** | Required if using S3 |

Generate a new secret:

```
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

## 3. Code state

- [x] Migrations generated and applied (`makemigrations --check` clean)
- [x] `manage.py check` — no issues
- [x] `manage.py check --deploy` — no warnings
- [x] `collectstatic` run; `staticfiles/` committed (132 files, 396 post-processed)
- [x] 131 tests passing
- [x] No hardcoded secrets in the tree
- [ ] Working tree is **dirty** — the migration-route work below is applied
      to production but not yet committed.

## 3a. Applying migrations to production

**This is required after any deploy that adds a migration.** Vercel has no
release phase and no shell, so deploying does *not* update the schema.

Incident, 2026-10-01: four migrations had been applied to the local database
only. `POST /login/` returned HTTP 500 with
`Unknown column 'accounts_user.otp_salt' in 'field list'` — `GET /login/`
still worked because it never queries that table, which is why the outage was
invisible until someone tried to sign in.

The database is **TiDB**, which rejects the single-statement form Django's
MySQL backend uses to add a foreign key column:

```
ALTER TABLE evidence ADD COLUMN uploaded_by_id bigint NULL,
  ADD CONSTRAINT ... FOREIGN KEY (uploaded_by_id) REFERENCES accounts_user (id)
-- (1072, "Key column 'uploaded_by_id' doesn't exist in table")
```

`crims/schema_ops.py` provides `SplitForeignKeyAddField`, which forces Django
down its deferred-constraint path and then waits for the new column to become
visible in `information_schema`, because TiDB publishes DDL asynchronously.
Any future migration that adds a FK column to a **new** column must use it.

Check for drift (read-only, safe at any time):

```bash
SECRET=$(cat .env.cron-secret)
curl -s -H "Authorization: Bearer $SECRET" \
  https://crims-eta.vercel.app/internal/migrate/
# {"status": "up-to-date", "applied": []}
```

Apply pending migrations (POST; each migration is its own transaction, so an
interrupted run can simply be repeated):

```bash
curl -s -X POST -H "Authorization: Bearer $SECRET" \
  https://crims-eta.vercel.app/internal/migrate/
```

The route is `csrf_exempt` on purpose — its authority is the bearer header, not
a cookie, so there is nothing for CSRF to protect. Without the exemption the
`curl` above fails with a 403. See `MigrationRouteTests` in
`accounts/test_auth_flows.py`.

**There is no pre-migration backup.** The production `DATABASE_URL` is a
Vercel secret and cannot be read from the CLI, so `mysqldump` against the live
database is not currently possible from a workstation. Take a provider-level
snapshot before large schema changes until that changes.

## 4. Security settings (verified active with `DEBUG=False`)

- [x] `SECURE_SSL_REDIRECT = True`
- [x] `SECURE_HSTS_SECONDS = 31536000`
- [x] `SECURE_HSTS_INCLUDE_SUBDOMAINS = True`
- [x] `SECURE_HSTS_PRELOAD = True`
- [x] `SESSION_COOKIE_SECURE = True`
- [x] `CSRF_COOKIE_SECURE = True`
- [x] `SESSION_COOKIE_HTTPONLY = True`
- [x] `SESSION_COOKIE_SAMESITE = 'Lax'`, `CSRF_COOKIE_SAMESITE = 'Lax'`
- [x] `SESSION_EXPIRE_AT_BROWSER_CLOSE = True`, 8-hour max age
- [x] `X_FRAME_OPTIONS = DENY`
- [x] `SECURE_CONTENT_TYPE_NOSNIFF = True`
- [x] `SECURE_REFERRER_POLICY = 'same-origin'`
- [x] `SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'`
- [x] Password hashing: PBKDF2 first
- [x] 4 password validators active
- [x] OTP generated with `secrets`, stored salted+hashed, purpose-bound
- [x] Uploads: extension allow-lists + size caps + randomised paths
- [x] 403/404/500 templates that leak no diagnostics

## 5. Database

- [x] Indexes on `status`/`created_at`, `citizen`/`created_at`, `priority`/`status`
- [x] Indexes on `role`/`is_approved`, `role`/`current_case_count`
- [x] Index on `wanted`, `complaint` (suspects), `evidence`/`-transferred_at`
- [x] `tracking_id` unique
- [x] Officer workload counters updated under `select_for_update()`
- [ ] Consider pagination — `activity_logs` and `ai_dashboard` render
      unbounded result sets (not a security issue; a scaling one)

## 6. Monitoring

- [x] `LOGGING` configured (was `{}`)
- [x] `django.request` logs 4xx/5xx
- [x] `crims.errors` logs permission denials and unhandled errors with a
      reference ID shown to the user on the 500 page
- [x] Failed verification emails are logged with the provider's error code
      and a redacted recipient (`accounts/utils.py`). Before this, a mail
      outage was indistinguishable from a user not receiving mail — which is
      how the current outage went undiagnosed.
- [x] `GET /health/` — returns `{"status":"ok","database":true}`; 503 if the
      database is unreachable. Point uptime monitoring at it.
- [ ] Point external monitoring at `/health/` (not yet configured)
- [ ] Vercel log drain / alerting for 5xx rate

## 7. Post-deploy verification (re-run after any change)

```bash
# These must all be 302 to /login/
for p in /pending-officers/ /reports/activity/ /analytics/crime-map/ \
         /analytics/ai-dashboard/ /analytics/ai-command-center/ \
         /complaints/officer/ /suspects/ /witnesses/ /investigations/; do
  curl -s -o /dev/null -w "%{http_code} %{redirect_url} $p\n" \
    "https://crims-eta.vercel.app$p"
done

# These must be 200
curl -s -o /dev/null -w "%{http_code} /\n"    https://crims-eta.vercel.app/
curl -s https://crims-eta.vercel.app/health/

# Login must render a form error, not a 500. The GET alone proves nothing,
# because only the POST path queries accounts_user.
curl -s -c /tmp/cj -o /dev/null https://crims-eta.vercel.app/login/
CSRF=$(grep csrftoken /tmp/cj | awk '{print $7}')
curl -s -b /tmp/cj -o /tmp/post.html -w "%{http_code}\n" \
  -X POST -e https://crims-eta.vercel.app/login/ \
  -d "csrfmiddlewaretoken=$CSRF" -d "username=__nobody__" -d "password=wrong" \
  https://crims-eta.vercel.app/login/
# expect 200, and the body to contain "correct username and password"
grep -q "correct username and password" /tmp/post.html && echo "login ok"
rm -f /tmp/cj /tmp/post.html
```

Then run the suite:

```bash
python manage.py test
python manage.py check --deploy
```
