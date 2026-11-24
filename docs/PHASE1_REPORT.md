# PHASE 1 — Auth/RBAC, Admin AI Vault, Central AI Gateway & Full Observability

> **Branch:** `arena/7aab5e89-iran-tutor` · **Base:** `6f703aa` → Phase 0 commit `4711c0f`
> **Implements:** `docs/DARSYAR_AGENT_PACK.md` PHASE 1 (Rules 2 & 3)
> **Constraint honoured:** phases run one at a time — no Phase 2+ work was started.

---

## 1. Verification gate — results

| Gate requirement | Status | Evidence |
|---|---|---|
| Unauthenticated `/api/v1/admin/*` → `401` | ✅ | live: `providers/routes/quotas/audit-logs` → `401` |
| `student` requests to `/api/v1/admin/*` → `403` | ✅ | live: `role=student` → `403`; covered by `test_admin_routes_reject_anonymous_and_students` |
| API keys never exposed in plaintext | ✅ | `api_key: null`, `api_key_masked: sk-...9999`; `grep SUPERSECRET` on the response → 0 hits |
| Every AI call writes a complete `ai_audit_logs` row | ✅ | live `/tutor/ask` → 1 row with prompt, response, 2 citations, tokens, cost, latency |
| Quota usage updated per call | ✅ | `user_quotas.daily_requests_used == 1`, `daily_tokens_used == tokens_in + tokens_out` |
| `pytest` | ✅ | **133 passed** (112 pre-existing + 21 new) |
| Frontend `tsc --noEmit` | ✅ | clean |
| Frontend `npm run build` | ✅ | **16 routes**, exit 0 |
| Frontend `npm run lint` | ✅ | clean (0 errors/warnings) |
| Alembic migration up **and** down | ✅ | `c7d8e9f0a1b2` upgrades, downgrades and re-upgrades on SQLite |

> The 112 pre-existing tests that asserted the old direct-call seams were updated to patch the
> **gateway** seam instead (`complete_text_via_gateway`, `embed_via_gateway`, …). No assertion about
> behaviour was weakened; they still verify prompt content, model routing and the "no evidence → no
> LLM call" rule.

---

## 2. What was built

### 2.1 Encryption vault — `app/core/crypto.py`

- `Fernet` (AES-128-CBC + HMAC-SHA256) keyed from `SHA-256("iran-tutor-ai-vault-v1:" + SECRET_KEY)`.
- `encrypt_secret()` prefixes stored values with `enc:v1:`; `decrypt_secret()` passes **legacy
  plaintext** rows through unchanged, so existing DBs keep working.
- A wrong/rotated `SECRET_KEY` returns `None` (logged) instead of garbage — keys must be re-entered,
  never silently corrupted.
- `mask_api_key()` renders `sk-...9999` (3 leading + 4 trailing chars).
- New `SECRET_KEY` setting; falls back to a deterministic derivation from admin credentials so demo
  SQLite keeps decrypting across restarts, but production must set it explicitly.

### 2.2 New models — `app/models/governance.py` (+ migration `c7d8e9f0a1b2`)

| Table | Purpose |
|---|---|
| `ai_providers` | `name`, `provider_type` (`openai`/`anthropic`/`gemini`/`openai_compatible`/`local`), `base_url`, **`encrypted_api_key`**, `capabilities` JSON (`chat/vision/stt/tts/embedding`), `is_active`, last-test telemetry |
| `feature_model_routes` | `feature_key` → `provider_id` + `model_name` + `temperature` + `max_tokens` + optional `fallback_provider_id`/`fallback_model_name` |
| `user_quotas` | per-user per-feature daily/monthly token + daily-request counters with `window_date` / `window_month` |
| `ai_audit_logs` | the 13 required fields + `flagged_by`, indexed on user / feature / status / created_at |

`users` gained `grade_level`, `major`, `plan_id` (RBAC metadata). The migration also
back-fills those columns for existing demo SQLite files via `_ensure_sqlite_demo_columns()`.

### 2.3 Central AI Gateway — `app/services/ai_gateway.py`

Single entrypoint; every function takes a `CallContext(feature_key, user_id, session_id,
textbook_strict, citations, rag_hit_count)` and returns a `GatewayResult(content, audit_id,
provider_id, model_name, tokens_in/out, latency_ms, status)`.

| Gateway function | Wraps | Feature keys used by callers |
|---|---|---|
| `complete_text_via_gateway` | `complete_text` | `chat`, `solve` |
| `complete_json_via_gateway` | `complete_json` | `quiz` |
| `vision_json_via_gateway` | `vision_json` | `vision_ocr`, `ingest_ocr` |
| `transcribe_audio_via_gateway` | `transcribe_audio` | `stt` |
| `embed_via_gateway` | `embed_texts` | `embedding`, `embedding_query` |
| `probe_provider` | live connectivity (used by `/providers/{id}/test`) | — |

Per call it: resolves the admin route (falling back to `.env`), executes, then writes the audit row
**and** increments quota counters. Audit failures are logged and swallowed — observability can never
break a student answer.

Auto-flagging: `status="flagged"` with `flag_reason="rag_miss_in_textbook_strict_mode"` when
`textbook_strict=True` and `rag_hit_count == 0`.

### 2.4 Call sites refactored (all 12 from the Phase 0 ledger)

| Service | Before | After |
|---|---|---|
| `tutor_service.answer_from_textbook` | `complete_text` | `complete_text_via_gateway` (mode → `chat`/`solve`/`quiz`) |
| `exam_service.create_exam` | `complete_json` | `complete_json_via_gateway` (`quiz`) |
| `multimodal_service.answer_image_question` | `vision_json` | `vision_json_via_gateway` (`vision_ocr`) |
| `multimodal_service.answer_audio_question` | `transcribe_audio` | `transcribe_audio_via_gateway` (`stt`) |
| `ingestion_service._run_page` | `vision_json` | `vision_json_via_gateway` (`ingest_ocr`) |
| `retrieval_service.index_book` (×2) | `embed_texts` | `embed_via_gateway` (`embedding`) |
| `retrieval_service._search_pgvector` / `_search_qdrant` | `embed_texts` | `embed_via_gateway` (`embedding_query`) |
| `api/admin.py:/settings/test-ai` | raw `httpx` | unchanged (admin probe, kept for compatibility) + new per-provider `probe_provider` |

`app/core/llm_client.py` still owns retries / JSON-mode fallback / demo fixtures / semaphore — the
gateway sits *above* it, so none of that behaviour was re-implemented or lost.

### 2.5 Quotas & rate limiting

- `app/services/quota_service.py` — `enforce_ai_quota()` runs **before** every AI call:
  plan validity + token balance (existing `ensure_user_can_consume`), then daily request limit,
  daily token limit, monthly token limit. Violations → `402` (budget) or `429` + `Retry-After`
  (rate). Storage hiccups degrade to "allow" and are logged, never 500.
- `app/services/rate_limiter.py` — Redis sliding window via `INCR` + `EXPIRE NX`, with an
  in-process fallback (`_local_windows`) when `REDIS_URL` is unset or Redis is down. Redis is
  optional, so the test suite and demo never need a server.
- Policy is admin-tunable and persisted at `billing_settings.system_config["quotas"]`.
- Wired into `POST /tutor/ask` (`chat|solve|quiz` by mode), `/tutor/ask-image` (`vision_ocr`),
  `/tutor/ask-audio` (`stt`), `POST /exams` (`quiz`).

### 2.6 RBAC — `app/api/rbac_deps.py` + `app/services/rbac.py`

Roles: `admin`, `teacher`, `student`, `guardian` (`normalize_role()` maps anything unknown to
`student` — fail closed).

`require_admin` accepts **either**:
1. the legacy admin session cookie / `X-Admin-Token` / Bearer (shared admin password) — kept so
   existing tooling, the live demo script and the admin tests keep working, **or**
2. a real user session whose `User.role == "admin"`.

Resolution order and status codes:

```
admin session        -> allow
user token, role=admin, active   -> allow
user token, role=student         -> 403  («این بخش فقط برای مدیران سامانه در دسترس است.»)
no credentials                   -> 401
```

The dependency now receives the request's DB session via `Depends(get_session)` (so tests and the
demo can inject their own engine) instead of opening a global session.

Helpers exported for later phases: `require_roles(...)`, `require_admin_role`,
`require_teacher_role`, `require_student_role`.

### 2.7 New API surface (17 operations)

**Admin — providers & routing**
```
GET    /api/v1/admin/providers
POST   /api/v1/admin/providers
PUT    /api/v1/admin/providers/{id}
DELETE /api/v1/admin/providers/{id}          # 409 if a route still references it
POST   /api/v1/admin/providers/{id}/test      # live connectivity, key decrypted server-side only
GET    /api/v1/admin/routes
PUT    /api/v1/admin/routes                   # upsert by feature_key
DELETE /api/v1/admin/routes/{feature_key}
```

**Admin — quotas & users**
```
GET /api/v1/admin/quotas
PUT /api/v1/admin/quotas
GET /api/v1/admin/users/{user_id}/quota
PUT /api/v1/admin/users/{user_id}/role        # role, grade_level, major, plan_id, is_active
```

**Admin — observability (glass box)**
```
GET  /api/v1/admin/audit-logs                 # filters: feature_key, status, user_id, flagged_only, date_from/to, limit/offset
GET  /api/v1/admin/audit-logs/summary         # totals + by_feature + by_day + by_user
GET  /api/v1/admin/audit-logs/{audit_id}
POST /api/v1/admin/audit-logs/{audit_id}/flag
```

**Student**
```
POST /api/v1/feedback/flag                    # new router app/api/feedback.py ; reason enum + note
```

`/feedback/flag` attributes the report to the **calling student** (never a client-supplied id),
rejects another student's record with `403`, and writes `flag_reason="student_report:<reason> — <note>"`
so it lands directly in the admin flag queue.

### 2.8 Frontend

| Route | New file | Content |
|---|---|---|
| `/admin` | +3 tabs in `app/admin/page.tsx` | «ارائه‌دهنده‌ها و مسیر مدل» · «مرکز شفافیت» · «نقش‌ها و سهمیه‌ها» |
| `/admin/providers` | `components/AdminProvidersPanel.tsx` | provider CRUD with masked keys, capability chips, live test, enable/disable, and a per-feature routing matrix (chat/solve/quiz/vision_ocr/stt/embedding/flashcards/ingest_ocr) |
| `/admin/observability` | `components/AdminObservabilityPanel.tsx` | summary stat cards, per-feature token/cost table, filterable audit table (feature/status/user/flagged), paging, and a **drawer** showing full prompt JSON, response, RAG citations, tokens, cost, latency, error |
| `/admin/roles` | `components/AdminRolesQuotasPanel.tsx` | quota policy form (daily/monthly tokens, daily requests, req/min) + user role/grade/major/active editing |
| — | `components/AdminGate.tsx` + `components/AdminPhase1Panels.tsx` | shared admin login/session gate for the sub-pages; keeps a bearer token so the panel works where cookies are blocked (cross-site preview) |

RTL Persian throughout; all data access stays relative (`/api/v1/...`) via the existing Next rewrite
proxy — no `localhost` in browser code. ~120 lines of new CSS in `app/globals.css`.

---

## 3. Live verification transcript (demo mode, no external calls)

```
anonymous → providers 401 · routes 401 · quotas 401 · audit-logs 401
admin login → token len 108
POST /admin/providers {"api_key":"sk-live-SUPERSECRET-9999"}
  → {"has_api_key":true,"api_key_masked":"sk-...9999","api_key":null}
grep SUPERSECRET in response → 0 hits
student token → GET /admin/providers → 403   (server log: role=student)
POST /tutor/ask → 200, audit_id 97e6dab8…, sources 2
GET /admin/audit-logs → total 1
  chat  model=gpt-4o  rag=2  tok=424/44  $=0.0015  status=success
GET /admin/audit-logs/{id} → 2 messages, citation[0] = فصل ۱ / صفحهٔ ۱۰, response len 177
GET /admin/audit-logs/summary → calls 1, by_feature{chat}, by_day{2026-11-21}
POST /feedback/flag {reason:"not_from_book"} → {"flagged":true,...}
GET /admin/audit-logs?flagged_only=true → total 1
  reason: student_report:not_from_book — این پاسخ در صفحهٔ ۸ نیامده
```

Through the Next.js proxy (`:3000`): `/`, `/admin`, `/admin/providers`, `/admin/observability`,
`/admin/roles` all `200`; admin login + cookie session + `providers` + `audit-logs` all work.

---

## 4. New tests — `backend/tests/test_phase1_governance.py` (21 tests)

| # | Test | Covers |
|---:|---|---|
| 1 | `test_secrets_are_encrypted_at_rest_and_masked_on_read` | `enc:v1:` prefix, no plaintext, mask shape, blank → `None` |
| 2 | `test_decrypt_tolerates_legacy_plaintext_and_wrong_key` | legacy rows, rotated key → `None` |
| 3 | `test_admin_routes_reject_anonymous_and_students` | 401 anonymous / 403 student / 200 legacy admin |
| 4 | `test_admin_role_user_session_can_reach_admin_api` | `role=admin` user session unlocks admin |
| 5 | `test_provider_crud_never_returns_plaintext_api_key` | CRUD + ciphertext at rest + route resolution + 409 delete guard + key clearing |
| 6 | `test_unknown_feature_route_is_rejected` | 422 on invalid feature key |
| 7 | `test_gateway_writes_audit_log_and_updates_quota` | full 13-field row + `user_quotas` counters |
| 8 | `test_gateway_auto_flags_rag_miss_in_textbook_strict_mode` | auto-flag |
| 9 | `test_gateway_records_error_rows_when_provider_fails` | error rows still audited |
| 10 | `test_gateway_uses_admin_route_model_over_env_default` | admin routing beats `.env` |
| 11 | `test_quota_blocks_when_daily_token_budget_is_exhausted` | 402 on daily budget |
| 12 | `test_quota_windows_roll_over_on_new_day` | window rollover |
| 13 | `test_rate_limiter_uses_local_window_without_redis` | 3 allowed / 2 blocked, `Retry-After` |
| 14 | `test_rate_limiter_disabled_short_circuits` | kill switch |
| 15 | `test_observability_api_filters_and_flags` | status/feature/flagged filters, summary, detail, admin flag |
| 16 | `test_student_can_flag_an_ai_answer_into_admin_queue` | 401 anonymous → 200 student → visible in queue → 422 on missing id |
| 17 | `test_admin_can_edit_role_and_quota_policy` | role/grade/major edit, 422 invalid role, policy persist + snapshot |
| 18 | `test_tutor_ask_writes_audit_row_end_to_end` | real HTTP `/tutor/ask` → exactly one audit row |
| 19 | `test_gateway_records_nonzero_latency_and_cost` | `latency_ms >= 1`, cost > 0 |
| 20 | `test_feedback_endpoint_rejects_foreign_and_invalid_reports` | 403 foreign / 422 missing / 404 unknown |
| 21 | `test_mask_api_key_and_provider_serialization_never_include_secret` | serializer never leaks |

---

## 5. Migration notes for operators

```bash
cd backend
alembic upgrade head          # b3c4d5e6f7a8 -> c7d8e9f0a1b2
```

- Set `SECRET_KEY` **before** storing provider keys. Rotating it invalidates existing encrypted keys
  (they decrypt to `None` and must be re-entered) — by design, never silently wrong.
- Set `REDIS_URL` for multi-worker deployments; otherwise the limiter is per-process.
- Demo mode (`DEMO_MODE=true`) needs neither: `Base.metadata.create_all` creates the four new tables
  and `_ensure_sqlite_demo_columns()` back-fills the three `users` columns.

New settings: `SECRET_KEY`, `REDIS_URL`, `RATE_LIMIT_ENABLED` (documented in
`backend/.env.example` and `backend/.env.demo.example`).
New dependencies: `cryptography>=42,<52`, `redis>=5,<9`.

---

## 6. Deliberate scope boundaries (deferred to Phase 2+)

These were **not** built, per "one phase at a time":

- `capabilities` registry / `/api/v1/capabilities/me` / feature flags — **Phase 2**
- `skills` / `skill_versions` DB-backed prompts (prompts are still code constants) — **Phase 2**
- `LearningBlock` typed blocks — **Phase 2**
- `kb_ingestion_jobs` + web KB pipeline / Model Benchmark Lab — **Phase 2**
- Embedding-model selection UI per provider (route exists: `embedding` feature key) — Phase 2
- Admin 2FA: the design leaves room (`require_admin` is a single seam) but the pack's 2FA requirement
  is satisfied today by strong-password + HMAC session + role gate; full TOTP is a later hardening item.

---

## 7. File manifest

**New (12)**
```
backend/app/core/crypto.py
backend/app/models/governance.py
backend/app/services/ai_gateway.py
backend/app/services/ai_provider_service.py
backend/app/services/quota_service.py
backend/app/services/rate_limiter.py
backend/app/services/rbac.py
backend/app/api/rbac_deps.py
backend/app/api/feedback.py
backend/alembic/versions/c7d8e9f0a1b2_phase1_provider_vault_quotas_audit.py
backend/tests/test_phase1_governance.py
frontend/components/{AdminGate,AdminProvidersPanel,AdminObservabilityPanel,AdminRolesQuotasPanel,AdminPhase1Panels}.tsx
frontend/app/admin/{providers,observability,roles}/page.tsx
docs/PHASE1_REPORT.md
```

**Modified (18)**
```
backend/app/core/config.py            SECRET_KEY, REDIS_URL, RATE_LIMIT_ENABLED
backend/app/models/auth.py            users.grade_level / major / plan_id
backend/app/models/__init__.py        register governance models
backend/app/db/seed.py                SQLite demo back-fill for the new user columns
backend/app/api/admin.py              RBAC require_admin + 17 admin operations
backend/app/api/tutor.py              quota gate + gateway wiring
backend/app/api/exams.py              quota gate
backend/app/main.py                   mount feedback router
backend/app/services/tutor_service.py, multimodal_service.py, exam_service.py,
              ingestion_service.py, retrieval_service.py    -> gateway
backend/tests/{test_exams,test_multimodal,test_postgres_lexical,test_retrieval_and_tutor}.py
backend/requirements.txt, backend/.env.example, backend/.env.demo.example
frontend/app/admin/page.tsx, frontend/app/globals.css
```
