# Hotfix Audit — AJAX UX, Phone/Password Auth, User & Role Administration

Date: 2026-11-22
Branch: `hotfix/user-auth-admin-management-20261122` (to be created from latest `main`)
Base commit: `9e22108` (Hotfix: secure provider routing and textbook-grounded learning)

This document is the Phase 1 (repository audit) and Phase 2 plan deliverable. It records
what exists today, what will be reused, and what must be added. The existing architecture is
preserved: FastAPI + async SQLAlchemy 2 + Alembic, Next.js RTL client, HMAC session tokens
backed by server-side `user_sessions` rows, and the `AiAuditLog` / `AdminActionLog`
glass-box trails.

---

## 1. Architecture rules reviewed

- `.kilocode/rules/architecture.md` — phase gating, "no hardcoded secrets/URLs/model names",
  Python 3.11+, Pydantic v2, SQLAlchemy 2 async, abstract SMS/payment providers, one LLM
  client wrapper, every phase ends with a verifiable test.
- `README.md` and `راهنمای-کامل-راه‌اندازی.md` — demo vs production profile, migrations
  (`alembic upgrade head`) are the only production schema mechanism.
- `.env.example`, `backend/.env.demo.example`, `app/core/production_guard.py` — weak-secret
  startup guard in `APP_ENV=production`.

## 2. Existing authentication

| Concern | Current implementation | Reuse / change |
|---|---|---|
| Phone normalization | `auth_billing_service.normalize_iranian_phone` (`+98`, `0098`, `98`, `09`, Persian digits) | Reuse unchanged; always normalize before uniqueness checks |
| OTP request | `POST /api/v1/auth/request-otp` — 6-digit code, per-IP limiter, resend cooldown, invalidates earlier codes | Reuse; add `purpose` (login/register/recover) |
| OTP verify | `POST /api/v1/auth/verify-otp` — `SELECT … FOR UPDATE`, TTL, `max_attempts`, HMAC-SHA256 hash of `otp_id:phone:code` | Reuse; add verified-registration handshake |
| Session token | HMAC-SHA256 over `user_id.expires.nonce`, key derived from `AUTH_SECRET`/`SECRET_KEY` (`core/signing.py`), every token must still have a live `user_sessions` row | Reuse; add rotation and revocation on privilege change |
| Session cookie | HttpOnly, `SameSite=None` + `Secure` on HTTPS, `Max-Age` = `USER_SESSION_TTL_SECONDS` | Reuse; keep `X-User-Token`/Bearer support (iframe previews, tests) |
| Logout | `POST /api/v1/auth/logout` revokes the `UserSession` row and clears cookie | Reuse |
| Admin auth | Legacy shared-password HMAC cookie `iran_tutor_admin` + `X-Admin-Token`/Bearer/`X-Admin-Username`/`X-Admin-Password`, **or** a user session whose role is `admin` (`require_admin`) | Keep legacy path; widen to `super_admin`; add re-authentication for sensitive mutations |
| SMS | `services/sms_provider.py` — demo / Kavenegar / SMS.ir / webhook behind an ABC | Reuse unchanged |
| Rate limiting | `services/rate_limiter.py` Redis sliding window with in-process fallback | Reuse for login, OTP request, OTP verify |

Gaps found:

1. No password credential at all (`users` has no password column) — login is OTP-only.
2. No `phone_verified_at`, so "unique verified phone" cannot be expressed.
3. No soft-delete / deactivation trail (`is_active` only), no audit of admin mutations on
   users except the coarse `AdminActionLog` writes in Phase 5 governance code.
4. Roles are a free-form `users.role` string validated only by three RBAC dependencies
   (`admin`, `teacher`, `student`/`guardian`); `super_admin` and `moderator` do not exist.
5. No protection against removing the last administrator; no escalation checks.
6. `PUT /api/v1/admin/users/{id}` can rewrite plan/tokens/activation but not name, phone,
   role or password; there is no create/delete endpoint and no account-audit view.
7. Frontend `AppProvider` modal only does OTP; there is no password field, no recovery flow.
8. Admin panel `/admin` keeps its active tab in React state only (lost on refresh), and the
   user list has no pagination/status/role filters.
9. No CSRF protection for cookie-authenticated mutations (session cookie + `SameSite=Lax`
   locally is the only mitigation today).

## 3. Database & migrations

- 20 Alembic revisions, single head `a4b5c6d7e8f9`. Conventions: UUID string PKs,
  `DateTime(timezone=True)` + `server_default=func.now()`, JSON with a `JSONB` variant,
  reversible `upgrade`/`downgrade`.
- `Base.metadata.create_all` is used **only** by the demo seeder and tests; production uses
  Alembic. New schema work therefore ships as a migration; the demo helper
  `_ensure_sqlite_demo_columns` is extended so existing demo SQLite files keep working.
- Financial history lives in `payment_transactions` and `token_usage_logs` with FK
  `user_id → users.id`; hard-deleting a user would orphan or violate those rows. This drives
  the soft-delete decision below.

## 4. Quotas, credits and audit

- Plans/credits: `plans`, `billing_settings`, `users.tokens_remaining/tokens_total`,
  `payment_transactions` (admin grants recorded with `provider="admin_grant"`).
- Enforcement: `quota_service` (policy in `billing_settings.system_config["quotas"]`,
  counters in `user_quotas`), called before every AI call.
- Audit: `ai_audit_logs` (AI calls), `admin_action_logs` (Phase 5 governance edits,
  `actor/action/target/payload_json`), `learning_evidence` review columns.

## 5. Existing tests (baseline)

- 35 backend test modules, `pytest -q` → **396 passed, 1 skipped** before this hotfix.
- Test islands use `sqlite+aiosqlite` in `tmp_path` with `Base.metadata.create_all` (demo
  only) and `app.dependency_overrides[get_session]`; the suite never needs a real `.env`.
- `backend/tests/conftest.py` forces `ADMIN_USERNAME=admin` / `ADMIN_PASSWORD=123` and
  disables the global rate limiter (limiter behavior is tested explicitly elsewhere).
- No frontend unit-test runner exists (no Jest/Vitest); frontend gates are `npm run lint`,
  `tsc --noEmit` and `next build` (CI job `frontend`).

## 6. Implementation plan

**Phase 2 — AJAX everywhere.** Add `frontend/lib/apiClient.ts` (fetch wrapper: JSON, error
normalization, CSRF header, 401 → session-expired event, in-flight de-duplication). Convert
the admin user-management surfaces and the auth modal to that client. Preserve filters in
the URL (`/admin?tab=users&q=…&role=…&page=…`) so a refresh keeps context. Loading, success,
error, confirm dialogs for destructive actions. Backend validation stays authoritative.

**Phase 3 — Phone + password.** New `core/passwords.py` (Argon2id via `argon2-cffi`, rehash
on verify). New service `services/auth_service.py`:
`request_otp(purpose)`, `verify_otp` → registration/recovery token for `register`/`recover`
purposes, `complete_registration`, `password_login`, `change_password`, `reset_password`.
Hashing never stores plaintext; login/OTP are rate limited per IP **and** per phone; sessions
rotate (new nonce, old row revoked) on login and on password/permission change; all sessions
revoked on password reset. Uniform error messages avoid enumeration.

**Phase 4 — Dev seed.** `db/dev_seed.py`, environment-controlled (`DEV_SEED_ENABLED`,
`DEV_SEED_*`), idempotent, insert-only, refuses to run when `APP_ENV=production`, stores only
an Argon2id hash, documented removal path.

**Phase 5 — Admin user management.** `services/permissions.py` (role ranks, least privilege,
`can_manage_user`), `services/admin_user_service.py` (create, update, role change, password
reset, activate/deactivate, soft delete, session inspection/revocation, quota, audit), new
router `api/admin_users.py` mounted at `/api/v1/admin/users` (new sub-paths only; existing
GET list and PUT update keep working and gain fields). Re-authentication (`X-Reauth-Password`)
for delete, admin creation and privilege elevation. Every mutation writes `AdminActionLog`.
Last active `super_admin` protected.

**Phase 6 — DB/API.** One reversible migration: `users.password_hash` (nullable),
`users.phone_verified_at`, `users.deleted_at` (+ index), `users.last_password_change_at`,
`otp_codes.purpose` (+ index), `unique` guard preserved on `phone_number`, index on
`users.role`, `users.is_active`. No `create_all` in runtime paths.

**Phase 7 — Frontend.** Auth modal state machine (phone → OTP → password for registration,
password login, OTP recovery), admin users screen, role/session/quota management, Persian RTL
copy, AJAX feedback.

**Phase 8 — Tests.** `backend/tests/test_user_auth_admin.py` covering the checklist in the
brief; frontend gates lint/typecheck/build.

**Phase 9 — Delivery.** Draft PR only; no merge, no deploy, no data loss.

## 7. Implementation status (Phases 2–8)

### Backend (complete)

| Area | File | Notes |
| --- | --- | --- |
| Password hashing | `backend/app/core/passwords.py` | Argon2id (64 MiB, t=3, p=4), policy (`MIN_PASSWORD_LENGTH=8`), transparent rehash, common-password blocklist. `argon2-cffi>=23.1` added to `requirements.txt`. |
| Auth service | `backend/app/services/auth_service.py` | Purpose-aware OTP (`register` / `recover` / `login`), handshake tokens, `password_login`, `complete_registration`, `change_password`, `reset_password`, session rotation + revocation. |
| Auth API | `backend/app/api/auth.py` | `/auth/login`, `/auth/register/{request-otp,verify-otp,complete}`, `/auth/password/{recover/request-otp,recover/verify-otp,recover/complete,change}`, `/auth/csrf`, `/auth/me`, `/auth/logout`. |
| CSRF | `backend/app/core/csrf.py` | `on` (default) = same-origin check for unsafe cookie methods; `strict` = + double-submit `iran_tutor_csrf` cookie/`X-CSRF-Token`; `off` for tooling only. |
| Permissions | `backend/app/services/permissions.py` | Rank-based matrix `student < guardian < teacher < moderator < admin < super_admin`; moderators are read-only. |
| Admin service | `backend/app/services/admin_user_service.py` | create / update / role / activation / password / delete (soft with history retention) / sessions / credits / audit. |
| Admin API | `backend/app/api/admin_users.py` | `/api/v1/admin/users` sub-resources (see §8). |
| Dev seed | `backend/app/db/dev_seed.py` | Insert-only, env-driven, production-refused, weak-password opt-in only. |
| Migration | `backend/alembic/versions/b7c1d2e3f4a5_phone_password_auth_user_admin.py` | Verified on PostgreSQL: upgrade → downgrade → upgrade. |
| Tests | `backend/tests/test_user_auth_admin.py` | 21 tests (see §9). |

### Frontend (complete)

| File | Purpose |
| --- | --- |
| `frontend/lib/apiClient.ts` | Single AJAX client: JSON body, CSRF header (`ensureCsrfToken` reads the cookie / `/auth/csrf`), `ApiError` taxonomy (`unauthorized`/`forbidden`/`validation`/`conflict`/`rate_limited`/`reauth_required`/`server`/`network`), Persian `detail` normalization, field-error extraction, 401 → `darsyar:session-expired`, in-flight de-duplication so a double click cannot double-submit. |
| `frontend/components/AuthFlowModal.tsx` | RTL state machine: password login, register (phone → OTP → password + confirm), password recovery, legacy SMS-code sign-in. Step indicator, password rules, demo-code helper only when the API discloses it, resend cooldown, no submit while busy. |
| `frontend/components/AdminUsersPanel.tsx` | Admin console: KPI summary, search + role/status/plan filters (mirrored into the URL), pagination, create user, profile edit, role change, password reset, activate/deactivate, soft delete, session list + individual/all revocation, quota/credit edit, audit history. Every destructive/privileged action goes through a confirmation dialog; role change, delete, password reset and staff creation also require the admin's own password (`X-Reauth-Password`). |
| `frontend/components/AppProvider.tsx` | Hosts `AuthFlowModal`, listens for `darsyar:session-expired` (clears client state, reopens the login modal with a Persian notice), attaches CSRF to `authFetch` mutations, drops the dead OTP-only modal state. |
| `frontend/app/admin/page.tsx` | Renders `AdminUsersPanel` at the top of the «کاربران» tab; the pre-existing billing/usage view is kept below unchanged. |
| `frontend/app/globals.css` | New RTL styles reused existing tokens (`modal-backdrop`, `exam-setup-modal`, `form-field`, `badge-pill`, `danger-button`). |
| `frontend/tests/*` | Vitest + Testing Library suite (see §9). `npm test` added. |

### Deliberate deviations

- **No email-based recovery.** The brief allowed it; the product is phone-first and there is
  no outbound email provider, so recovery is OTP-over-SMS only.
- **Hard delete only when no history exists.** Accounts with payments, usage logs or files are
  soft-deleted (`deleted_at`, password cleared, sessions revoked) so financial and audit
  records stay intact.
- **CSRF defaults to origin checking, not token checking.** Native/API clients without a
  session cookie would otherwise break; `CSRF_ENFORCEMENT=strict` enables full double-submit.

## 8. API surface added or modified

**New (auth)**

- `POST /api/v1/auth/login` — `{phone_number, password}` → session token + user + `csrf_token`.
- `POST /api/v1/auth/register/request-otp` → `{phone_number, resend_after_seconds, demo_code?}`.
- `POST /api/v1/auth/register/verify-otp` → `{verified, otp_token}` (handshake only, no account yet).
- `POST /api/v1/auth/register/complete` → creates the account, sets the password, returns a session.
- `POST /api/v1/auth/password/recover/request-otp`, `/recover/verify-otp`, `/recover/complete`.
- `POST /api/v1/auth/password/change` — authenticated, requires the current password.
- `GET /api/v1/auth/csrf` — issues/echoes the CSRF token for cookie sessions.

**New (admin, all under `/api/v1/admin/users`, RBAC-enforced server-side)**

- `GET /roles` · `GET /audit`
- `POST ""` (create; `X-Reauth-Password` required for `admin`/`super_admin`)
- `GET /{id}` · `PATCH /{id}`
- `PUT /{id}/role` (reauth when elevating or when the target is staff)
- `PUT /{id}/activation`
- `POST /{id}/password` (always reauth; revokes sessions)
- `DELETE /{id}?hard_delete=false` (always reauth; soft by default)
- `GET /{id}/sessions` · `DELETE /{id}/sessions/{session_id}` · `POST /{id}/sessions/revoke-all`
- `GET /{id}/credits` · `PUT /{id}/credits`
- `GET /{id}/audit`

**Modified (backwards compatible)**

- `GET /api/v1/admin/users` — keeps the legacy payload keys and gains `pagination`, `filters`
  and role counts; `limit=` still maps to page 1.
- `GET /api/v1/auth/me` — adds `csrf_token` **only** for cookie sessions.
- `POST /api/v1/auth/request-otp` / `verify-otp` — split per-IP (router) and per-phone
  (service) limits; `demo_code` is returned only in demo mode.

## 9. Test results

- Backend: `cd backend && pytest -q` → **417 passed, 1 skipped** (baseline before this
  hotfix was 396 passed, 1 skipped). `tests/test_user_auth_admin.py` alone: **21 passed**
  (Argon2id round-trip/policy, full registration + duplicate phone, OTP expiry + attempt
  limit + purpose isolation, resend cooldown, password login success/failure/rotation, login
  rate limit per phone, recovery revoking every session, change-password, permission matrix
  (escalation blocked), admin create + role assignment, admin profile/phone/password edits,
  role change + last-super_admin protection, deactivation revoking sessions + delete retaining
  history, list filters/pagination/sessions, quotas + audit integrity, legacy admin payload
  contract, dev-seed idempotency, dev-seed production refusal, weak-password opt-in, CSRF
  strict + default modes).
- Migration: PostgreSQL `upgrade head` → `downgrade -1` → `upgrade head` verified.
- Frontend: `npx tsc --noEmit` clean, `npm run lint` → 0 errors (14 pre-existing warnings),
  `npm run build` succeeds (23 routes), `npm test` → **26 passed** across 3 files
  (`apiClient.test.ts` 10, `AuthFlowModal.test.tsx` 8, `AdminUsersPanel.test.tsx` 8).
- CI (`.github/workflows/ci.yml`, run on the draft PR) → **both jobs green**:
  `Backend tests and migrations` (pytest against PostgreSQL + `alembic upgrade head` on a fresh
  database) and `Frontend lint and build`. The workflow now also runs `npm test` between lint
  and build, and `npm test` is a documented `package.json` script.

## 9.1 Delivery

| Item | Value |
| --- | --- |
| Branch | `arena/69c88cea-iran-tutor` (cut from `main` @ `9e22108`) |
| Commits | `abc2a76` implementation · `fbe35e5` CI wiring |
| Pull request | https://github.com/mahakas/iran-tutor/pull/33 (**Draft**, base `main`) |
| Merged / deployed | No — intentionally left as a draft |

## 10. Manual test script

1. **Register.** Open `/`, click «ورود / ثبت‌نام», choose «ثبت‌نام با موبایل», enter a fresh
   `09XXXXXXXXX`, submit → the OTP step appears (in demo mode the code is shown). Verify the
   code → the password step appears; mismatch shows an inline Persian error and sends nothing;
   matching passwords create the account and log you in without a page reload.
2. **Login.** Log out (the confirmation dialog now posts through the AJAX client), then sign in
   with mobile + password — no SMS is sent.
3. **Recovery.** «رمز عبورم را فراموش کرده‌ام» → OTP → new password. Afterwards, an existing
   other browser session must be logged out (sessions revoked).
4. **Dev seed.** With `DEV_SEED_ENABLED=true`, `DEV_SEED_PASSWORD=123`,
   `DEV_SEED_ALLOW_WEAK_PASSWORD=true`, restart twice: exactly one `mahdi` account exists and
   its data is not overwritten. Set `APP_ENV=production` and restart: the seed refuses to run.
5. **Admin.** `/admin` → «کاربران»: search by phone/name, filter by role/status/plan, page
   through results; refresh the browser — tab, filters and page survive (they live in the URL).
   Open a user, change the role → the confirm dialog demands your own password; cancel sends
   nothing. Deactivate → sessions are revoked. Reset the password → sessions revoked, re-login
   with the new password works. Delete → account is soft-deleted and no longer appears under
   «فعال». Change the quota → tokens update inline. Sessions tab → revoke one and then all.
6. **Session expiry.** Delete the session token in devtools and perform any admin mutation: the
   panel locks and the login modal reopens with a Persian notice instead of a blank page.
7. **Last super admin.** Try to demote/delete the only active `super_admin`: the API answers
   409 with a Persian message and the UI shows it inline.

## 11. Remaining security concerns

- `ADMIN_USERNAME`/`ADMIN_PASSWORD` default to `admin`/`123` in `config.py`. The legacy admin
  login is still supported for backwards compatibility; it must be replaced before any real
  deployment (documented in the production guard, not fixed here to avoid breaking existing
  production logins).
- The demo SMS provider prints the OTP; `DEMO_MODE=false` plus a real `SMS_PROVIDER` is
  required in production.
- CSRF `on` mode relies on `Origin`/`Referer`; a reverse proxy that strips both headers will
  weaken it. Keep `CSRF_ENFORCEMENT=strict` for browser-only deployments.
- Rate limiting for login/OTP is in-process (per worker). A multi-worker deployment should move
  the counters to Redis (already a dependency).
- No 2FA/TOTP yet for `super_admin` accounts; re-authentication via password is the only
  second factor.
