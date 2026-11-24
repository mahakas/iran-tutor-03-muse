# PHASE 0 — Codebase Inventory & Baseline Verification

> **Repository:** `mahakas/iran-tutor` · **Branch:** `arena/7aab5e89-iran-tutor` · **Base commit:** `6f703aa` (merge of PR #15)
> **Audit date:** 2026-11-21
> **Scope:** Read-only audit. No production code was modified in this phase.
> **Governing document:** [`docs/DARSYAR_AGENT_PACK.md`](./DARSYAR_AGENT_PACK.md) and `.kilocode/rules/architecture.md`

---

## 1. Baseline verification results (Verification Gate)

| Check | Command | Result |
|---|---|---|
| Backend test suite | `cd backend && pytest -q` | ✅ **112 passed** in 5.83 s (exit 0) |
| Frontend typecheck | `cd frontend && npx tsc --noEmit` | ✅ **0 errors** (exit 0) |
| Frontend production build | `cd frontend && npm run build` | ✅ **Compiled successfully** — 13 routes prerendered, exit 0 |
| Python runtime | `python3 --version` | 3.11.2 |
| Node runtime | `node --version` / `npm --version` | v22.22.3 / 10.9.8 |
| Next.js / React | from `package.json` | next 16.4.6 (Turbopack), react 19.3.1 |

Setup used for the run (all artifacts are git-ignored):

```bash
cd backend && python3 -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt
cd frontend && npm install
```

Notes recorded during the baseline run:

- The test suite needs **no** `.env`, no API key, no PostgreSQL and no Qdrant. `backend/tests/conftest.py` injects placeholder env vars (`DEMO_MODE=false`, dummy `LLM_BASE_URL`, in-memory/unused `DATABASE_URL`) via `os.environ.setdefault`.
- `npm install` rewrote `frontend/next-env.d.ts` (`.next/dev/types` → `.next/types`). That file is generated; it was reverted and **must stay out of phase commits**.
- A temporary `backend/.env` (copied from `.env.demo.example`) was needed only to introspect the app for the endpoint list; it was deleted afterwards. `.env` is git-ignored.

### 1.1 Test distribution (112 collected)

| Tests | File |
|---:|---|
| 39 | `tests/test_phase1_d.py` (PDF ingestion engine) |
| 11 | `tests/test_exams.py` |
| 11 | `tests/test_admin_api.py` |
| 8 | `tests/test_retrieval_and_tutor.py` |
| 6 | `tests/test_multimodal.py` |
| 6 | `tests/test_admin_control_center.py` |
| 4 | `tests/test_phase6_auth_plans.py` |
| 4 | `tests/test_demo_mode.py` |
| 4 | `tests/test_account_and_settings.py` |
| 3 | `tests/test_tutor_api.py` |
| 3 | `tests/test_postgres_lexical.py` |
| 3 | `tests/test_pdf_rendering.py` |
| 2 | `tests/test_hybrid_rag.py` |
| 2 | `tests/test_curriculum_api.py` |
| 2 | `tests/test_admin_appearance_and_search.py` |
| 1 | `tests/test_tutor_modes.py` |
| 1 | `tests/test_llm_wrappers.py` |
| 1 | `tests/test_demo_database.py` |

---

## 2. Repository layout

```
.
├── .kilocode/rules/architecture.md      # persistent domain + coding rules
├── docker-compose.yml                   # postgres:16, qdrant v1.12.4, redis:7
├── .env.example                         # root: only POSTGRES_* vars
├── backend/
│   ├── app/{core,db,models,services,api}
│   ├── alembic/{env.py,versions/*}
│   ├── scripts/{ingest_book,index_book,test_ingest,test_llm,verify_ai_stack}.py
│   ├── tests/                           # 18 files / 112 tests
│   ├── requirements.txt, pytest.ini
│   ├── .env.example, .env.demo.example
│   └── storage/                         # runtime PDFs/pages (git-ignored)
├── frontend/                            # Next.js 16 App Router, RTL
│   ├── app/{page,layout,admin/*,account/*}
│   ├── components/*.tsx
│   └── lib/*.ts
├── scripts/run-live-demo.sh
└── docs/{DARSYAR_AGENT_PACK.md, PHASE0_INVENTORY.md}
```

**No separate worker/queue process exists.** Background work is in-process (`FastAPI BackgroundTasks`).

---

## 3. Database: models, tables, migrations

### 3.1 ORM models (14 tables)

`app/models/__init__.py` imports all of them so Alembic autogenerate sees everything.

**`app/models/curriculum.py`** — content domain
| Table | Key columns | Notes |
|---|---|---|
| `grades` | `number` (unique), `title`, `has_major` | grades 1–12; `has_major` true for 10–12 |
| `majors` | `code` (unique), `title` | `math_physics`, `experimental`, `humanities` |
| `books` | `title`, `grade_id`→grades, `major_id`→majors (nullable), `pdf_file_path`, `total_pdf_pages`, `status` enum(`created/ingesting/ready/failed`) | |
| `book_pages` | `book_id`, `pdf_page_index`, `printed_page_number`, `chapter_number`, `chapter_title`, `markdown_content`, `original_markdown_content`, `visual_elements` JSON, `page_image_path`, `status` enum(`pending/done/failed/needs_review`), `error_message`, `extraction_model`, `prompt_tokens`, `completion_tokens`, `warnings` JSON, `edited_by_human` | unique `(book_id, pdf_page_index)` — this is the grounding unit for citations |

**`app/models/auth.py`** — identity & billing
| Table | Key columns |
|---|---|
| `plans` | `code`, `name`, `price_toman`, `token_quota`, `storage_quota_bytes`, `duration_days`, `is_active`, `sort_order` |
| `billing_settings` | singleton `id=1`, `token_price_per_1k_toman`, `starter_tokens`, `starter_duration_days`, `starter_storage_bytes`, `admin_preferences` JSON, **`system_config` JSON** |
| `users` | `id` uuid str, `phone_number` (unique), `full_name/first_name/last_name/email/avatar_path`, **`role`** (default `student`), `preferences` JSON, `plan_code`, `plan_title`, `tokens_total/tokens_remaining/tokens_used_total`, `plan_started_at/plan_expires_at`, `is_active`, `last_login_at` |
| `otp_codes` | `phone_number`, `code_hash`, `attempts`, `max_attempts`, `expires_at`, `consumed_at` |
| `payment_transactions` | `user_id`, `plan_code`, `amount_toman`, `provider`, `authority`, `ref_id`, `status`, `paid_at` |
| `token_usage_logs` | `user_id`, `action`, `book_id`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_toman`, `created_at` |
| `user_sessions` | `user_id`, `token_nonce` (unique), `user_agent`, `ip_address`, `last_seen_at`, `expires_at`, `revoked_at` |
| `user_files` | `user_id`, `original_filename`, `storage_path`, `mime_type`, `category`(image/audio/file), `size_bytes`, `source_context`, `chat_session_id`, `book_id`, `status` |

**`app/models/chat.py`**
| Table | Key columns |
|---|---|
| `chat_sessions` | `book_id`, `user_id` (nullable str), `grade_number`, `major_code`, `mode`, `title`, **`messages` JSON (entire transcript)** |

**`app/models/exam.py`**
| Table | Key columns |
|---|---|
| `exam_sessions` | `book_id`, `user_id`, `grade_number`, `major_code`, `title`, `exam_type`(konkoor/final), `time_limit_seconds`, `status`, **`questions` JSON (incl. private answer keys)**, `submitted_answers` JSON, `report_card` JSON, `expires_at`, `submitted_at` |

### 3.2 Migration chain (`backend/alembic/versions/`)

Single linear head: `a04a943af8b1 → 7562ccf427ce → c398e215d1aa → d4f8b92a1e3c → e5a7c1d39b2f → f1a2b3c4d5e6 → a2b3c4d5e6f7 → b3c4d5e6f7a8` (the last one is `head`).

| Revision | Purpose |
|---|---|
| `a04a943af8b1` | initial: `grades`, `majors`, `books`, `book_pages` |
| `7562ccf427ce` | `book_pages.edited_by_human` |
| `c398e215d1aa` | `exam_sessions` |
| `d4f8b92a1e3c` | `chat_sessions` |
| `e5a7c1d39b2f` | phase-6 auth: `plans`, `billing_settings`, `users`, `otp_codes`, `payment_transactions`, `token_usage_logs` |
| `f1a2b3c4d5e6` | profiles: `users.first_name/last_name/email/avatar_path/preferences`, `user_sessions`, `user_files`, plan storage quotas |
| `a2b3c4d5e6f7` | `billing_settings.admin_preferences` + `book_pages.original_markdown_content` |
| `b3c4d5e6f7a8` | `billing_settings.system_config` **(head)** |

**Phase 1+ migrations must branch from `b3c4d5e6f7a8`.**

### 3.3 Demo / SQLite compatibility (must not break)

Two distinct boot paths exist — this is the main migration hazard:

1. **Demo path** (`DEMO_MODE=true`, `DATABASE_URL=sqlite+aiosqlite:///./demo.sqlite3`): `seed_database()` in `app/db/seed.py` calls `Base.metadata.create_all` — **Alembic is never run**. Schema comes straight from the models.
2. **Production path**: `alembic upgrade head` on PostgreSQL.

Consequences for every new migration:

- Every new table/model **must** be created both by a migration *and* be reachable through `Base.metadata` (import in `app/models/__init__.py`), otherwise the demo DB silently lacks it.
- SQLite has no `JSONB`, no `ENUM`; models already use `JSON().with_variant(JSONB, "postgresql")` — copy that pattern.
- `_ensure_sqlite_demo_columns()` in `seed.py` is a hand-written column back-fill for pre-existing demo SQLite files. New `NOT NULL` columns on `users`/`billing_settings` need an entry there (or a server_default) or old demo DBs break at startup.
- `ingestion_service.upsert` branches on `session.get_bind().dialect.name == "sqlite"` (`sqlite_insert` vs `pg_insert`) — keep that pattern for new bulk upserts.
- `admin.py` `/settings/test-vector` explicitly reports "SQLite can't do pgvector" and falls back to lexical search.

---

## 4. API surface (`/api/v1/...`)

**81 documented operations** across 7 routers, all mounted in `app/main.py`.

| Router | Prefix | Endpoints |
|---|---:|---|
| `api/auth.py` | `/api/v1/auth` | `POST /request-otp`, `POST /verify-otp`, `GET /me`, `PUT /me`, `POST /logout` |
| `api/tutor.py` | `/api/v1/tutor` | `POST /ask`, `POST /ask-image`, `POST /ask-audio`, `GET /sessions`, `POST /sessions`, `GET /sessions/{id}`, `PUT /sessions/{id}`, `DELETE /sessions/{id}` |
| `api/exams.py` | `/api/v1/exams` | `POST ""`, `GET ""`, `GET /{exam_id}`, `POST /{exam_id}/submit` |
| `api/curriculum.py` | `/api/v1/curriculum` | `GET /grades`, `GET /majors`, `GET /books`, `GET /search` |
| `api/plans.py` | `/api/v1/plans` | `GET ""`, `POST /checkout`, `POST /verify`, `GET /verify`, `GET /usage` |
| `api/account.py` | `/api/v1/account` | profile (GET/PUT), avatar (POST/GET/DELETE), `phone/request-otp`, `phone/verify`, preferences (GET/PUT/reset), `storage`, `storage/files` (GET/POST, GET/DELETE `{file_id}`, GET `/content`), sessions (GET, DELETE `{id}`, POST `/revoke-others`), `search` |
| `api/admin.py` | `/api/v1/admin` | see below |
| misc | — | `GET /health`, `GET /api/v1/system/status` |

### 4.1 Admin endpoints (31 operations)

`admin.py` builds **two** routers and merges them (`router.include_router(protected_router)`):

- `router` (public): `GET /auth/session`, `POST /auth/login`, `POST /auth/logout`
- `protected_router` — guarded by the `Depends(require_admin)` dependency:

```
books:      POST /books/upload-and-ingest · GET /books · GET /books/{id}/status
            GET /books/{id}/pages · GET /books/{id}/pages/{idx}/image
            PUT /books/{id}/pages/{idx} · GET /books/{id}/preview (HTML)
            PATCH /books/{id} · POST /books/{id}/reindex · POST /books/{id}/reprocess
            DELETE /books/{id}
billing:    GET /billing · PUT /billing/settings · PUT /billing/plans/{plan_code}
users:      GET /users · PUT /users/{user_id} · GET /users/{user_id}/usage
            GET /users/{user_id}/sessions · POST /users/{user_id}/revoke-sessions
prefs:      GET /preferences · PUT /preferences · POST /preferences/reset
search:     GET /search
dash:       GET /overview
settings:   GET /settings · PUT /settings · POST /settings/reset
            POST /settings/test-ai · POST /settings/test-vector · POST /settings/test-sms
```

---

## 5. Current authentication & authorization (gap analysis for Phase 1)

### 5.1 What exists

| Mechanism | Implementation | Where |
|---|---|---|
| **Admin session** | HMAC-SHA256 signed cookie `iran_tutor_admin` (`{expires}.{nonce}.{sig}`), key derived from `admin_username + admin_password + llm_api_key`. TTL `ADMIN_SESSION_TTL_SECONDS` (12 h). Also accepts `x-admin-token`, `Authorization: Bearer`, and (legacy) `x-admin-username`/`x-admin-password`. | `api/admin.py:70-153`, `require_admin()` |
| **Student session** | Signed token, nonce persisted in `user_sessions`, revocable. Accepted via `x-user-token`, `Bearer`, or `DARSYAR` cookie. | `services/auth_billing_service.py`, `api/dependencies.py` |
| **Student OTP** | `otp_codes` + hashed code, TTL/attempts/resend limits from settings. | `api/auth.py` |
| **SMS abstraction** | `SmsProvider` ABC with `demo`, `kavenegar`, `sms_ir`, `webhook` implementations. | `services/sms_provider.py` ✅ already pluggable |
| **Payment abstraction** | `demo` and `zarinpal` providers. | `services/payment_provider.py` |
| **Quotas** | `ensure_user_can_consume()` (plan expiry + remaining tokens) and `record_and_deduct_usage()` (writes `token_usage_logs`, decrements user counters) called at the start/end of tutor & exam handlers. | `services/auth_billing_service.py` |

### 5.2 Gaps (Phase 1 must close)

1. **Admin is a single shared password — there is no admin *user* and no role model in the auth path.** `users.role` exists in the DB (`default="student"`) but **nothing in the codebase ever checks it**. A `student` token therefore has no meaning at `/api/v1/admin/*` — that's currently only protected by the separate cookie/HMAC scheme.
2. **No `teacher` / `guardian` behaviour anywhere.** Roles required by the pack (`admin`, `teacher`, `student`, `guardian`) are unimplemented.
3. **No `grade_level`, no `major`, no `plan_id` column** on `users` (only `plan_code` + `plan_title` strings). `is_active` exists.
4. **No rate limiting anywhere** — no sliding window, no Redis usage at all (see §7).
5. **`record_and_deduct_usage` is coarse** — one `action` string, token counters only; no per-feature quotas, no daily/monthly windows.
6. **No 2FA / no password login for admin users** beyond the shared secret in `Settings`.

### 5.3 Admin credential & key handling today

- Settings are `admin_username` (default `admin`) and `admin_password` (default `123`) — a plain match with `hmac.compare_digest`.
- **AI keys live in `billing_settings.system_config` (JSON, plaintext)** and are overlaid onto process settings by `app/core/runtime_config.py`. `RUNTIME_SECRET_FIELDS = (llm_api_key, audio_api_key, embedding_api_key, sms_api_key, zarinpal_merchant_id)`.
- Secrets are already **masked** on read: `mask_secret()` + `serialize_admin_settings()` never return plaintext (`llm_api_key → sk-…xxxx` style).
- **There is no encryption at rest.** `system_config` stores the API key as plain text in the database — the `ai_providers.encrypted_api_key` requirement (Fernet/AES-GCM keyed from `SECRET_KEY`) is entirely new work. Note there is currently **no `SECRET_KEY` setting**; `auth_secret` exists but is optional, and the admin HMAC key is derived from the admin password.

---

## 6. Existing AI / Vision / STT / Embedding / Qdrant call sites

### 6.1 The single LLM wrapper — `app/core/llm_client.py` (598 lines)

Everything already funnels through this module (good news for Phase 1's gateway requirement):

| Public function | Provider client | Used by |
|---|---|---|
| `complete_text(model, messages)` | `_get_client()` → `AsyncOpenAI(llm_base_url, llm_api_key)` | `services/tutor_service.py:128` |
| `complete_json(model, messages)` | same | `services/exam_service.py:283` |
| `vision_json(model, sys, user, png)` | same | `services/ingestion_service.py:239`, `services/multimodal_service.py:49` |
| `embed_texts(texts, model?)` | `_get_embedding_client()` → `embedding_base_url`/`embedding_api_key` | `services/retrieval_service.py:254,279,465,538` |
| `transcribe_audio(bytes, …)` | `_get_audio_client()` → `audio_base_url`/`audio_api_key` | `services/multimodal_service.py:86` |
| `track_token_usage()` / `record_token_usage()` | ContextVar `UsageAccumulator` | `api/tutor.py` wraps each request |

Cross-cutting behaviour already inside the wrapper (must be preserved by `ai_gateway`):

- `MAX_RETRIES = 3` + exponential backoff with jitter for 429/5xx/timeouts/`InvalidJSONError`.
- Global `asyncio.Semaphore(max_concurrency)`.
- JSON-mode fallback: caches models that reject `response_format=json_object` in `_json_mode_unsupported`.
- `extract_json()` — three-stage recovery (raw → fenced → outermost braces, string-aware).
- Demo-mode fixtures for every function (`_demo_questions`, canned tutor replies, canned transcript, synthetic vision output).
- `close_llm_clients()` + `refresh_runtime_clients()` for hot-reload of admin runtime config.

### 6.2 Call sites that must be re-routed through `ai_gateway`

| # | Location | Kind | Feature key (proposed) |
|---:|---|---|---|
| 1 | `services/tutor_service.py:128` `complete_text(tutor_model)` | chat | `chat` / `solve` / `question_designer` (by `mode`) |
| 2 | `services/tutor_service.py:103` `search_textbook()` | RAG retrieval | (pre-call step of the gateway) |
| 3 | `services/exam_service.py:283` `complete_json(tutor_model)` | chat (JSON) | `quiz` |
| 4 | `services/exam_service.py:218` `search_textbook()` | RAG retrieval | pre-call step |
| 5 | `services/multimodal_service.py:49` `vision_json(vision_model_primary)` | vision | `vision_ocr` (student photo) |
| 6 | `services/multimodal_service.py:86` `transcribe_audio()` | stt | `stt` |
| 7 | `services/ingestion_service.py:239` `vision_json(primary / escalation)` | vision | `ingest_ocr` (admin, offline) |
| 8 | `services/retrieval_service.py:254,279` `embed_texts()` (indexing) | embedding | `embedding_index` |
| 9 | `services/retrieval_service.py:465,538` `embed_texts()` (query) | embedding | `embedding_query` |
| 10 | `api/admin.py:1863` `/settings/test-ai` — raw `httpx` `GET /models` + `POST /chat/completions` | connectivity probe | `provider_test` |
| 11 | `api/admin.py:1970` `/settings/test-vector` — raw `httpx` to Qdrant | connectivity probe | `vector_test` |
| 12 | `scripts/ingest_book.py` → `ingest_book_pages` | vision (CLI, offline) | `ingest_ocr` |
| 13 | `scripts/index_book.py` → `index_book` | embedding (CLI) | `embedding_index` |
| 14 | `scripts/test_ingest.py`, `scripts/test_llm.py`, `scripts/verify_ai_stack.py` | model A/B + smoke | `benchmark` |

**No direct `AsyncOpenAI(` construction exists outside `llm_client.py`.** The only raw HTTP AI calls are #10 (admin connection test) and #11 (Qdrant probe).

### 6.3 Retrieval stack — `app/services/retrieval_service.py` (23 KB)

- Two backends selectable by `VECTOR_BACKEND`: `qdrant` (default) or `pgvector` (Supabase).
- Hybrid fusion: PostgreSQL **lexical** search (`_search_postgres`, `simple` FTS) ⟷ vector search (`_search_qdrant` / `_search_pgvector`), fused by **reciprocal-rank fusion** in `merge_hybrid_results()`.
- Hard scoping: `make_textbook_filter()` + `search_textbook()` filter by `grade_number`, `major_code`, `book_id`; only `PageStatus.done` pages are indexed (human-reviewed).
- Persian text normalisation: `normalize_persian_text()`, `build_lexical_query()`.
- Point ids: `_point_id(book_id, pdf_page_index)`.
- `demo_mode` uses a deterministic offline token-hash embedding (`embed_texts`) so the whole RAG path runs with no provider.
- **No cross-grade / multi-grade retrieval, no `concept_links`, no PageIndex** → Phase 4 work.

---

## 7. Observability & logging today

| Layer | What exists | Gap vs. Pack Rule 3 |
|---|---|---|
| **Token usage** | `token_usage_logs` (`user_id`, `action`, `book_id`, tokens, `cost_toman`, `created_at`) written by `record_and_deduct_usage`; aggregate shown in `/admin/overview` & `/admin/users/{id}/usage` | **No prompt, no response text, no model/provider id, no latency, no cost in USD, no RAG citations, no flagging, no per-call row for vision/STT/embedding.** |
| **Per-request accumulation** | `ContextVar` `UsageAccumulator` via `track_token_usage()` in `api/tutor.py` | In-memory only; lost on error paths |
| **Page extraction** | `book_pages.extraction_model`, `prompt_tokens`, `completion_tokens`, `warnings` | Ingestion only |
| **App logs** | `logging` with structured JSON payloads (`_log(level, event, **fields)`), events `llm.*.ok/retry/failed`, `sms.otp.*` | Logs, not queryable via `/admin` |
| **Admin UI** | `/admin/overview` (aggregate stats), `/admin/users/{id}/usage` (token history), `AdminOverviewPanel.tsx` | **No audit-log table, no filterable call log, no prompt/response inspector** |

**Redis is in `docker-compose.yml` but is not used by any code** (`grep -ri redis backend/app` → 0 hits; `redis` is not in `requirements.txt`). Rate limiting and recoverable streaming (Phases 1 & 4) therefore need a new `redis` dependency.

---

## 8. Frontend inventory (Next.js 16 App Router, RTL, `dir="rtl"` on `<html>`)

### 8.1 Routes (13 prerendered)

| Route | File | Purpose |
|---|---|---|
| `/` | `app/page.tsx` → `components/StudentApp.tsx` (1 927 l) | The **entire student app** — curriculum picker, tutor chat, image/voice upload, timed exam runner, exam history |
| `/admin` | `app/admin/page.tsx` (3 262 l) | The **entire admin panel** — single page with tabs |
| `/account/settings` (+ `appearance`, `general`, `notifications`, `privacy`, `storage`) | `app/account/**` | Student settings shell |
| `/account/profile`, `/account/help`, `/account/upgrade` | `app/account/**` | Profile, help, plan upgrade |

### 8.2 Admin tabs (all inside `app/admin/page.tsx`)

`overview` · `books` · `plans` · `users` · `integrations` · `appearance`

| Tab | Component | Content |
|---|---|---|
| overview | `AdminOverviewPanel.tsx` (515 l) | aggregate KPIs |
| books | inline in `page.tsx` | upload PDF → ingest, page preview / manual markdown edit, reindex/reprocess/delete |
| plans | inline | `billing_settings` + 3 plans CRUD |
| users | inline | user list, plan/quota edit, session revoke, token usage |
| integrations | `AdminIntegrationsPanel.tsx` (1 260 l) | **AI base URL + key (5 sections)**: execution mode & main AI endpoint, per-model routing matrix (`vision_model_a/b`, `vision_model_primary`, `vision_model_escalation`, `tutor_model`, `speech_to_text_model`, `embedding_model`), vector backend, SMS gateway, payment gateway |
| appearance | `AdminAppearancePanel.tsx` (770 l) | theming, persisted in `billing_settings.admin_preferences` |

`GlobalSearch.tsx` (792 l, ⌘K palette), `DiffViewer.tsx` + `lib/diff.ts` (manual page-edit diff), `MathContent.tsx` + `lib/math.ts` (KaTeX), `ThemedSelect`, `ExamRunner`.

### 8.3 Frontend conventions Phase 1+ must follow

- **All data access is relative** (`/api/v1/...`); `next.config.ts` rewrites `/api/:path*` → `BACKEND_ORIGIN` (default `http://127.0.0.1:8000`). No `localhost` in browser code. Proxy limits: `proxyClientMaxBodySize: 105mb`, `proxyTimeout: 120s`.
- **Student auth**: token in `sessionStorage` (`iran_tutor_user_token`), sent as `Authorization: Bearer` + `X-User-Token` (`AppProvider.tsx` exports `buildUserAuthHeaders`, `readStoredUserToken`, `storeUserToken`).
- **Admin auth**: admin cookie is HTTP-only; `/admin` currently just calls `GET /api/v1/admin/auth/session` and renders a login card — **no route-level guard, no middleware, no role check**.
- **Theming**: client-side preference engine in `lib/preferences.ts` (595 l) writing `data-*` attributes on `<html>`; admin prefs cached in `localStorage`.
- **i18n**: `lib/i18n.ts` (`COPY` object, `fa`/`en`).
- Styling is plain CSS (`app/globals.css`) + Tailwind 4 postcss pipeline; **no component library, no data-fetching library** (hand-rolled `fetch`).

---

## 9. Scripts (`backend/scripts/`, `scripts/`)

| Script | Role | Notes for Phase 2 |
|---|---|---|
| `backend/scripts/ingest_book.py` | CLI: `--pdf --grade --major --title --start --end [--force --only-failed --overwrite-human --dry-run]` | Thin wrapper over `ingestion_service.ingest_book_pages(...)` — **already a reusable service**, so Phase 2's "refactor CLI into a service" is mostly about a job table + progress + admin trigger, not about moving code |
| `backend/scripts/index_book.py` | `--book-id --batch-size` → `retrieval_service.index_book()` | already service-backed |
| `backend/scripts/test_ingest.py` | A/B two vision models → `compare.html` | seed for Phase 2 **Model Benchmark Lab** |
| `backend/scripts/test_llm.py` | single vision smoke test | |
| `backend/scripts/verify_ai_stack.py` | smoke: text, JSON, vision, embeddings | |
| `scripts/run-live-demo.sh` | idempotent demo launcher (venv + npm i + uvicorn `0.0.0.0:8000` + `next dev 0.0.0.0:3000`) | useful for the live-preview workflow |

`ingestion_service.ingest_book_pages()` signature already accepts `progress_callback`, `start_page`, `end_page`, `force`, `only_failed`, `overwrite_human`, `dry_run` — i.e. resume/re-index primitives exist. What's missing is a persisted `kb_ingestion_jobs` row and cancellation.

---

## 10. Configuration surface

`app/core/config.py` (`Settings`, pydantic-settings, `backend/.env`) + `app/core/runtime_config.py` (DB overlay, hot-applied).

| Group | Fields |
|---|---|
| Mode | `demo_mode` |
| AI | `llm_base_url`, `llm_api_key`, `llm_timeout`, `max_concurrency`, `vision_model_a/b/primary/escalation`, `tutor_model`, `speech_to_text_model`, `audio_base_url`, `audio_api_key`, `escalate_figures` |
| Embeddings/vector | `vector_backend` (`qdrant`/`pgvector`), `qdrant_url`, `qdrant_collection`, `embedding_base_url`, `embedding_api_key`, `embedding_model`, `embedding_dimension` |
| Admin auth | `admin_username`, `admin_password`, `admin_session_ttl_seconds` |
| Student auth | `auth_secret` (optional), `user_session_ttl_seconds`, `otp_ttl_seconds`, `otp_resend_seconds`, `otp_max_attempts`, `sms_provider`, `sms_api_key`, `sms_sender`, `sms_template`, `sms_webhook_url` |
| Payment | `payment_provider`, `zarinpal_merchant_id`, `zarinpal_sandbox`, `public_app_url` |
| DB | `database_url` |

- Admin-editable (persisted in `billing_settings.system_config`): everything in `RUNTIME_PUBLIC_FIELDS` (30 fields) + `RUNTIME_SECRET_FIELDS` (5 secrets, write-only & masked on read).
- **There is no `SECRET_KEY`** — Phase 1 needs one to key the Fernet/AES-GCM vault. `auth_secret` is optional and unused for the admin path.
- Design intent per `.kilocode/rules/architecture.md`: *"No hardcoded secrets, URLs, or model names: everything comes from `.env`"*, *"All LLM calls go through ONE client wrapper module"* — both currently honoured, but the *"per-feature model routing"* of the Pack is only a flat set of globals today (`feature_model_routes` doesn't exist).

---

## 11. Known deviations from the Pack (work ledger for Phases 1–6)

| # | Pack requirement | Current state | Phase |
|---:|---|---|---|
| 1 | RBAC with `admin`/`teacher`/`student`/`guardian` | `users.role` column exists, **never enforced**; admin auth is a separate shared-password cookie | 1 |
| 2 | `users.grade_level`, `major`, `plan_id` | absent (`plan_code`/`plan_title` strings only) | 1 |
| 3 | `ai_providers` + `feature_model_routes` tables | absent; keys in `billing_settings.system_config` **plaintext JSON** | 1 |
| 4 | Encrypted key vault (Fernet/AES-GCM from `SECRET_KEY`) | absent; `mask_secret()` only masks output | 1 |
| 5 | `plans` + `user_quotas` + Redis sliding-window limiter | `plans` exists; **no `user_quotas`, no rate limiter, Redis unused/uninstalled** | 1 |
| 6 | `ai_audit_logs` (13 fields, flagging) | only `token_usage_logs` (aggregate counters) | 1 |
| 7 | `POST /api/v1/feedback/flag` | absent | 1 |
| 8 | `/admin/observability` UI | absent (overview KPIs only) | 1 |
| 9 | `capabilities` registry + `/api/v1/capabilities/me` | absent; student nav hardcoded in `StudentApp.tsx` | 2 |
| 10 | `skills` / `skill_versions` DB-backed prompts | prompts hardcoded in `tutor_service.SYSTEM_PROMPT`, `multimodal_service.IMAGE_QUESTION_SYSTEM_PROMPT`, `exam_service` inline | 2 |
| 11 | `LearningBlock` typed blocks | absent; answers are single markdown strings | 2 |
| 12 | `kb_ingestion_jobs`, web KB pipeline, `source_figures` | `BackgroundTasks` + `progress_callback` only; figures stay inside `book_pages.visual_elements` JSON descriptions | 2 |
| 13 | Flashcards / SM-2 / Anki | absent | 3 |
| 14 | `learner_memories` L1/L2/L3 | absent (`chat_sessions.messages` is the whole transcript) | 4 |
| 15 | Multi-grade Konkoor RAG + `concept_links` | `search_textbook` filters to **one** `book_id`; no cross-grade graph | 4 |
| 16 | Recoverable SSE streaming, stop/regenerate | **no streaming at all** — `POST /tutor/ask` returns a full JSON body | 4 |
| 17 | Chat search + recycle bin | absent (`DELETE /tutor/sessions/{id}` is hard delete) | 4 |
| 18 | Mistake bank, quiz validator, deep solve, mastery path | absent (`validate_questions` is structural only) | 5 |
| 19 | Notebook, Mermaid/SVG visualize, Living Book, TTS | absent; TTS has **no** provider at all in `llm_client` | 6 |

### 11.1 Extra observations that constrain later phases

- `chat_sessions.messages` and `exam_sessions.questions` store **whole transcripts/answer keys in one JSON column** — fine now, but Phase 4 streaming + Phase 5 mistake bank will need row-level messages.
- `user_id` on `chat_sessions` / `exam_sessions` is a loose `String(64)` **without a foreign key** to `users` — Phase 1 should consider tightening this without breaking demo data.
- `require_student` is the only role-aware dependency and it does **not** check `role`.
- The admin panel is one 3 262-line client component; adding `/admin/observability`, `/admin/providers`, per-user memory pages will require extracting shared admin layout/nav (single-page tabs are already at the edge of maintainability).
- `frontend` has **zero tests**; the only quality gate is `tsc --noEmit` + `next build` + `eslint`.
- No Redis client, no Alembic autogenerate usage documented, no CI workflow file (`.github/` does not exist) — tests are run manually.

---

## 12. Phase 0 conclusion

**Baseline is green and safe to build on:**

- ✅ `pytest -q` → 112 passed
- ✅ `tsc --noEmit` → clean
- ✅ `npm run build` → 13 routes, success
- ✅ Inventory written (`docs/PHASE0_INVENTORY.md`)
- ✅ Zero production files modified in this phase (only `frontend/next-env.d.ts` regenerated by `npm run build` and immediately reverted)

**Ready for Phase 1.** The natural entry points are:

1. `app/core/llm_client.py` — wrap with `app/services/ai_gateway.py` (5 existing functions + audit hook + quota pre-check), keeping all retry/JSON-mode/demo behaviour.
2. `app/api/admin.py` — split `require_admin` into a real role dependency; add the provider vault, quota, and audit endpoints.
3. `billing_settings.system_config` — migrate the 5 plaintext secrets into `ai_providers.encrypted_api_key` without breaking the runtime-overlay mechanism.
4. New Alembic migration off `b3c4d5e6f7a8`, mirrored by `Base.metadata` + `_ensure_sqlite_demo_columns()` for demo SQLite.
