# Release Readiness (Phase 7)

Branch: `arena/67538167-iran-tutor` (base `c0497ca`, Phase 6 merged).
Scope: security audit and hardening, configuration parity, production guards, and verification.
Product features are unchanged except where listed under section 2.

## 1. Verification results (this revision)

| Check | Result |
|---|---|
| `pytest -q tests` (default environment) | **308 passed, 1 skipped** |
| `pytest -q tests` with `PHASE4_PG_URL` set (real PostgreSQL 16.2) | **309 passed, 0 skipped** |
| Phase 7 targeted tests (`test_phase7_hardening.py`, `test_phase7_followup.py`) | 10 + 14 = 24 passed |
| `alembic upgrade head` on a fresh **PostgreSQL 16.2** database | OK (head `d4e5f6a7b8c9`) |
| `alembic check` on the same PostgreSQL database | **No new upgrade operations detected** |
| `alembic downgrade c3d4e5f6a7b8` then `upgrade head` (PostgreSQL) | OK (migration is reversible) |
| `alembic check` on the SQLite development database | Dialect-only type drift (`JSONB`→`JSON`), unchanged from the previous audit; not a schema gap |
| `tsc --noEmit` | Clean (exit 0) |
| `npm run build` | Passed |
| Production start on PostgreSQL (`APP_ENV=production`, strong secrets) | `GET /health` → `{"status":"ok","mode":"production"}`; `GET /api/v1/curriculum/grades` → 200 |
| Production start with weak secrets (`ADMIN_PASSWORD=123`, no `SECRET_KEY`) | Refused at startup (uvicorn exit 3) with the reason in the log |

### PostgreSQL environment used for these results

Docker is not available in the audit sandbox, and there was no system PostgreSQL. The results above
come from an **embedded PostgreSQL 16.2** server (`pgserver` 0.1.4, a real Postgres binary) running
on a Unix socket. It is a genuine PostgreSQL server, so migrations and queries are real, but it is
not the production container.

**First action before any deployment:** run `alembic upgrade head` and `alembic check` against the
production PostgreSQL (section 4, step 2). Do this before starting the API.

## 2. Work completed in this revision

### 2.1 Student access to source figures (`/api/v1/curriculum/books/{book_id}/figures/{figure_id}/image`)

- Previously the student reader (`/study/[bookId]`) got figure metadata from
  `/api/v1/immersive/books/{id}/pages/{n}` (student-scoped, `ready` books only) and showed captions
  only. It never loaded image bytes, so it did not use the admin route.
- A new read-only endpoint now serves figure images to students. It requires `require_student`,
  checks the `immersive_reader` capability, returns 404 unless the book is `ready`, requires the
  figure to belong to that book, and refuses any path outside that book's `figures/` folder.
- `/api/v1/admin/kb/figures/{id}/image` is unchanged and still admin-only.
- Tests: `test_student_figure_image_only_for_ready_books`,
  `test_student_figure_image_refuses_paths_outside_book_folder`.
- **Note:** the reader UI now renders these images: `FigureThumb` is wired in the «شکل‌ها» tab
  and inline below the page image in `ImmersiveReader`. The open item is now
  discoverability/inline rendering + tests (done in this change).

### 2.2 Production startup guard (`app/core/production_guard.py`)

- New setting `APP_ENV` (alias `ENVIRONMENT`), default `local`.
- With `APP_ENV=production` (or `prod`), startup raises `RuntimeError` and stops when:
  - `ADMIN_PASSWORD` is `123`, a known weak value, shorter than 12 characters, or starts with
    `change_me` / `replace_with`;
  - `SECRET_KEY` is missing, shorter than 32 characters, or a placeholder.
- Outside production, nothing is blocked. The existing admin-password warning still logs.
- `.env.example` placeholders are rejected in production on purpose, so the operator must replace them.
- Tests: 7 cases in `test_phase7_followup.py`, including the `ENVIRONMENT` alias.

### 2.3 Per-capability quota and textbook grounding guard (Phase 5 open items)

**Per-capability quota.**
- Usage counters were already stored per `feature_key` in `user_quotas`. The limits were global, so
  every capability shared one cap value.
- Limits can now be overridden per capability under `billing_settings.system_config.quotas.per_feature`.
  Omitted fields inherit the global value.
- Enforcement (`enforce_ai_quota`, the per-minute rate bucket, and `get_quota_snapshot`) uses the
  effective limits for the feature.
- Admin API: `GET /api/v1/admin/quotas` (now also returns `feature_overrides`),
  `PUT /api/v1/admin/quotas/features/{feature_key}`, and `DELETE /api/v1/admin/quotas/features/{feature_key}`.
  Keys must match `^[a-z][a-z0-9_]{1,63}$`.
- The global `PUT /api/v1/admin/quotas` previously overwrote the whole quotas block. It now keeps
  the overrides. This was found while writing the test.
- `/admin` → "سقف مصرف به‌تفکیک قابلیت" section: lists overrides, adds or updates one, and removes one.
- Test: `test_per_capability_quota_override_is_isolated_and_admin_managed`.

**Textbook grounding guard (`app/services/grounding_guard.py`).**
- Runs inside `capability_runtime` (`run_capability_text` and `run_capability_json`) for every call
  scoped to one book. It checks the citations against the database:
  - the book exists and is `ready`;
  - each citation has the same `book_id` (no cross-book references);
  - each `pdf_page_index` exists in that book;
  - each `printed_page_number` equals the stored value.
- A suspicious result **never blocks** the answer. It is written to `ai_audit_logs` as a `flagged`
  decision row with `flag_reason=grounding_mismatch` and the issue list.
- Check failures are logged and never raise into the request path.
- `record_decision_audit` accepts a `status` argument for this purpose.
- Tests: correct citations pass, and wrong printed page, cross-book, missing page, and not-ready book
  are each flagged. A runtime wiring test confirms `run_capability_text` calls the guard.

### 2.4 Feedback flag ownership

- The rule requested is: allow the flag when `audit.user_id == current_user.id` or `audit.user_id is None`,
  otherwise refuse. **The current code already implements exactly this** (`if row.user_id is not None and row.user_id != user.id` → 403).
  A tighter variant from the previous session was reverted because it broke the existing product test.
- Added the negative test `test_student_cannot_flag_another_users_audit_row`: another student's row
  returns 403 and is not modified.
- `test_student_can_flag_an_ai_answer_into_admin_queue` still passes unchanged.

### 2.5 PostgreSQL drift fix (migration `d4e5f6a7b8c9`)

Found by running `alembic check` on real PostgreSQL. Only PostgreSQL is affected:
- `plans.code`, `users.phone_number`, and `user_sessions.token_nonce` had a `uq_*` unique constraint
  beside a plain `ix_*` index, while the models declare a single unique `ix_*` index. Uniqueness was
  already enforced, so the fix only aligns the names and makes the enforcement match the model.
- `flashcard_decks.user_id` and `flashcard_reviews.user_id` were `VARCHAR(64)` in the database and
  `VARCHAR(36)` in the models. User ids are UUIDs (36 characters), so the width is aligned to the model.
- The migration is reversible (`downgrade` restores the previous shape; verified).

### 2.6 Also in this revision

- `/admin` quota copy now says "برای هر کاربر و هر قابلیت" (the counters are per capability).
- `.env.example` documents `APP_ENV`.
- `docker-compose.yml` has a header comment that points to the production runbook.

## 3. Skipped test explained

The single skip in a default `pytest` run is `tests/test_phase4_postgres_smoke.py:30`:
`set PHASE4_PG_URL to run the PostgreSQL smoke test`.

- It exercises `create_all`/`drop_all` on a real PostgreSQL database, so it cannot run on SQLite.
- It is skipped by design when `PHASE4_PG_URL` is not set (CI and the local default do not have a PostgreSQL server).
- With `PHASE4_PG_URL` pointing at PostgreSQL 16.2 it **passes** (309 passed, 0 skipped).
- **Warning:** the smoke test drops every table at teardown. Never point `PHASE4_PG_URL` at a database
  you want to keep. Use a dedicated, empty database.

## 4. Production run (exact sequence)

Run from the repository root. Use a dedicated PostgreSQL database for production.

**Step 1: configure secrets (once, never commit them).**
```bash
cp .env.example .env            # Compose variables (POSTGRES_*)
cp .env.example backend/.env    # backend settings
```
Edit `backend/.env` and set at least:
`APP_ENV=production`, `DATABASE_URL=postgresql+asyncpg://USER:PASS@HOST:5432/DB`,
`ADMIN_PASSWORD` (12+ characters, not a placeholder), `SECRET_KEY` (32+ characters,
e.g. `python3 -c "import secrets;print(secrets.token_urlsafe(48))"`), `LLM_BASE_URL`, `LLM_API_KEY`,
the `VISION_MODEL_*` values, and `DEMO_MODE=false`.

**Step 2: start infrastructure (PostgreSQL, Qdrant, Redis).**
```bash
docker compose up -d postgres qdrant redis
```
Compose binds these ports to `127.0.0.1` only.

**Step 3: install the backend and migrate. Stop if either command fails.**
```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
.venv/bin/alembic check        # must print: No new upgrade operations detected.
```

**Step 4: start the API (single worker: the rate limiter is in-process when Redis is not set).**
```bash
APP_ENV=production .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```
Check: `curl -s http://127.0.0.1:8000/health` must return `{"status":"ok","mode":"production"}`.

**Step 5: build and start the web app (in another terminal, from the repository root).**
```bash
cd frontend
npm ci
BACKEND_ORIGIN=http://127.0.0.1:8000 npm run build
BACKEND_ORIGIN=http://127.0.0.1:8000 npm run start -- -p 3000
```
The Next.js server proxies `/api/*` to `BACKEND_ORIGIN`, so the browser never reaches the API directly.
Put a TLS reverse proxy in front of port 3000 (and do not expose 8000 or the infrastructure ports).

## 5. Open items and residual risk

- **Feedback flag on an unowned audit row (accepted, low):** a student who knows the id of an audit row
  with `user_id = NULL` can add a flag. The flag only adds a queue entry and changes no content.
  Revisit if audit ids become guessable.
- **Grounding guard is detect-and-flag only:** it does not remove or rewrite citations. Admins must
  review `grounding_mismatch` rows in the audit queue.
- **Quota counters are per capability:** a user's daily cap applies to each capability separately,
  not to all capabilities combined. The per-capability override makes this explicit. A combined cap
  would be a separate change.
- **`ADMIN_PASSWORD` default in code is now empty (changed 2026-11-24, §7):** `config.py`
  no longer defaults to `"123"`; with no value set the legacy shared-password admin login
  is disabled. `ADMIN_PASSWORD` must be set explicitly (12+ characters) before any admin
  login works, and production still refuses to start with a weak value.
- **Image endpoint is now used by the reader UI** (section 2.1): `FigureThumb` renders figure
  images in the «شکل‌ها» tab and inline below the page image.
- **Docker not verified in this sandbox:** the Compose file is infrastructure-only and its only change is a comment.
  Run `docker compose config` on the target host.
- **Earlier carry-over:** the Phase 5 open item for a deterministic text-to-book check outside Living Book is now
  covered by the shared grounding guard. Its scope is citation validation, not semantic answer checking.

## 6. Earlier audit results (unchanged from the first revision)

- **IDOR candidates verified scoped:** `deep_solve_service.get_owned`, `notebook_service` (`_owned_notebook`,
  `_owned_block`), `flashcard_sources` (`user_id` checks), `mistake_bank_service._owned`, account storage
  (`user_id` and `status=active`), and `api/kb.py` figure image (router-level `require_admin`).
  Since the first revision: flashcard book-source generation now enforces the same
  ready+grade gate as tutor/exams (`api/flashcards.py`), and the KB figure-image endpoint
  now confines reads to that book's own figures directory (`api/kb.py`).
- **Uploads:** `services/upload_guard.py` checks magic bytes for personal uploads, chat audio (against the
  declared MIME type), and admin PDF uploads. Admin stored suffixes are server-chosen.
- **Persian search:** `services/search_normalize.py` folds `ي/ك/ة` and ZWNJ for chat and curriculum search
  (Python and SQL sides). RAG already normalized these.
- **Provider probe audit:** every `probe_endpoint` call writes a `provider_probe` audit row without the key.
- **Secrets:** provider responses return `api_key: None`. `probe_endpoint` scrubs keys from errors. No
  `NEXT_PUBLIC_*` secrets and no frontend console logging.
- **XSS:** SVG is sanitized with DOMPurify plus an allowlist, and never during SSR. Mermaid runs with
  `securityLevel: "strict"` after a safety check.
- **AI governance:** SDK and HTTP calls for AI live only in `core/llm_client.py`, reached only through `ai_gateway.py`.
- **Capabilities:** `api/exams.py` enforces the `quiz` capability. Account, curriculum, and kb routes have no
  capability check, and they are not AI-backed (kb is admin-only).
- **Content serving:** HTML is served as `text/plain` unless downloaded, with `nosniff`.

## 7. Professional redesign + hardening (2026-11-24, uncommitted working-tree changes)

Baseline before this pass (measured in-sandbox): `tsc --noEmit` clean,
`vitest run` 20 files / 170 tests passed, `npm run build` exit 0,
`pytest -q` 516 passed, 2 skipped, 2 SAWarnings. Final verification results are
recorded by the coordinator in the handoff report; the suite totals below are the
baseline + 1 new regression test (517 tests).

### Redesign (frontend only, no API/route changes, Persian copy unchanged)

- `frontend/app/globals.css`: complete design-token system (spacing, radius, shadow,
  typography, focus-ring scales) and a full `[data-theme="dark"]` token block replacing
  scattered dark overrides. Contrast fix: `--muted` `#76828b` (~3.9:1) → `#5d686f`
  (~5.8:1 on canvas). Unified skeleton/empty/error states, `:focus-visible` rings,
  `prefers-reduced-motion` support, mobile polish.
- `StudentHomeDashboard` / `StudentSideNav` / `StudentApp` / admin page: consistent
  cards, buttons and states; `aria-label`s on dashboard sections and nav landmarks,
  `role="alert"` on errors, `role="status"` on loading/typing indicators.

### Hardening (backend only)

- `core/config.py`: no default admin password (was `"123"` → `""`); legacy
  shared-password login is disabled until one is set explicitly. Tests are unaffected
  (conftest forces `ADMIN_PASSWORD=123`).
- `core/production_guard.py`: weak-password list widened
  (`1234`, `123456`, `111111`, `admin123`, `password1`, `qwerty`, `letmein`, …).
- `api/admin.py`: second, global per-username admin-login rate-limit bucket
  (50 attempts / 900 s) alongside the existing per-IP bucket.
- `api/flashcards.py`: book-source flashcard generation now enforces the ready+grade
  gate (`enforce_student_book_grade_level`); new regression test
  `test_generate_from_book_rejects_non_ready_book_without_model_call`.
- `api/kb.py`: figure-image reads confined to that book's own figures directory.
- `services/rate_limiter.py`: in-process fallback buckets capped at 10,000 with
  oldest-first eviction (was unbounded).
- `core/csrf.py`: unused non-browser exemption dead code removed (no behavior change).
- Verified sound and left unchanged: session cookies/rotation/revocation, CSRF
  `on`/`strict` modes, OTP/login rate limits, IDOR/ownership checks, upload
  magic-byte guards, secret scrubbing in provider probes, grounding guard.
  The legacy shared-secret admin path is intentionally kept (HOTFIX §11): removing it
  would break the whole admin test suite and existing tooling; it needs a product
  decision, not a hardening pass.

### Known remaining limitations (not fixed here)

- `tests/test_phase6_rich_study.py::test_handoff_parallel_posts_create_single_block`
  was a pre-existing timing flake in the parallel-handoff dedupe (`with_for_update`
  is a no-op on SQLite, so two parallel POSTs could both pass the duplicate check).
  Fixed 2026-11-24 in `notebook_service.add_block` with a process-local
  `asyncio.Lock` around the check-and-insert (the row lock remains the
  cross-process guard on PostgreSQL); the test now passes 5/5 runs and the full
  `test_phase6_rich_study.py` file passes 50/50. The same SQLite limitation
  exists in `create_notebook`'s `dedupe_by_book` path, which has no failing test
  and was left unchanged.
- The 2 SAWarning non-checked-in-connection warnings are a GC-timing artifact that does
  not reproduce on the individual tests; left unchanged.
- Out of scope, unchanged: real-model / real-SMS / real-PostgreSQL / real-Redis
  validation, free-text exam grading (MCQ-only by design), NULL audit-row flagging
  (audit #8, documented risk), retiring the legacy admin path.
