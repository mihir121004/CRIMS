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

- [ ] **Gmail OAuth refresh token.** The local token returns HTTP 401. A
      failure no longer 500s registration (fixed and tested), but no email
      can be delivered, so no user can complete email verification and no
      password reset can work. Registration now fails loudly with a form
      error rather than silently.

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
- [x] 105 tests passing
- [x] No hardcoded secrets in the tree
- [x] Working tree clean at `b88cf14`

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
```

Then run the suite:

```bash
python manage.py test
python manage.py check --deploy
```
