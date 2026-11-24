# REDESIGN — Baseline اجرا و موجودی واقعی (فاز ۰۰)

> **تاریخ اجرا:** ۲۰۲۶-۱۱-۲۳
> **دامنه:** فقط مستندسازی؛ هیچ فایل کد، migration یا پیکربندی اجرایی تغییر نکرده است.
> **منبع:** آرشیو `iran-tutor-hotfix-auto-publish.zip` (پوشهٔ `iran-tutor-main`)
> **سندهای این فاز:** همین فایل + `REDESIGN_STATUS_MATRIX.md` + `REDESIGN_PHASE_00_REPORT.md`

---

## ۱. روش اجرا و محیط

این baseline از **کد و اجرای واقعی تست‌ها** استخراج شده است، نه از مستندات. ترتیب کار مطابق قواعد مشترک بود: شناسایی ریشهٔ مخزن → خواندن اسناد → ثبت وضعیت git → inventory کامل → اجرای تست‌ها → تطبیق مستندات با کد.

| مورد | مقدار واقعی |
|---|---|
| ریشهٔ مخزن | `iran-tutor-main/` شامل `backend/` و `frontend/` (تأیید شد) |
| وضعیت git | آرشیو zip فهرست `.git` ندارد (خروجی بدون تاریخچه). در محیط اجرا، کل پوشه به‌عنوان untracked زیر مخزن والد (`main` @ `ef56c37`) دیده می‌شود. **هیچ commit/push انجام نشد** |
| Python | 3.12.16 (venv اختصاصی از `requirements.txt` ساخته شد) |
| Node / npm | v24.22.3 / 11.19.1 (نصب با `npm ci` از `package-lock.json`) |
| FastAPI نصب‌شده | 0.128.0 |
| Next / React | 16.4.6 / 19.3.1 (از lock) |
| eslint / vitest / typescript / tailwind | 9.39.5 / 3.2.7 / 5.9.3 / 4.3.5 (از lock) |
| سرویس‌های بیرونی | PostgreSQL/Qdrant/Redis در این سندباکس اجرا نشدند؛ همهٔ تست‌ها مسیر SQLite/ایزوله رفتند |
| آرتیفکت‌های اجرایی ساخته‌شده | `.venv/`، `frontend/node_modules/`، `.next/` — همگی در `.gitignore` پوشش داده شده‌اند؛ `next-env.d.ts` با نسخهٔ آرشیو بایت‌به‌بایت یکسان باقی ماند |

> یادداشت: `npm run build` بدون تغییر در `next-env.d.ts` تمام شد (با diff با نسخهٔ آرشیو بررسی شد).

---

## ۲. نمودار معماری فعلی (از کد استخراج شده)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ مرورگر (RTL، فارسی)                                                          │
│  StudentApp.tsx (+ صفحات feature)  ·  /admin (AdminSideNav + پنل‌ها)          │
│  AuthFlowModal · apiClient.ts (fetch + CSRF + 401→session-expired)           │
│  توکن دانش‌آموز: sessionStorage["iran_tutor_user_token"] + کوکی iran_tutor_user│
└───────────────▲──────────────────────────────────────────────┬───────────────┘
                │  همهٔ درخواست‌ها نسبی /api/*                  │
┌───────────────┴──────────────────────────────────────────────▼───────────────┐
│ Next.js 16 (App Router) — rewrite `/api/:path*` → BACKEND_ORIGIN             │
└──────────────────────────────────────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼────────────────────────────────────────────┐
│ FastAPI (backend/app/main.py) — Modular Monolith، بدون microservice          │
│  middleware: security-headers · CSRF (core/csrf.py: on/strict/off)           │
│  lifespan: production_guard · seed_database (demo) · runtime_config          │
│            · recover_stale_podcast_jobs (heartbeat sweep)                    │
│  ۲۲ router: auth · account · admin · admin_users · curriculum · plans ·      │
│  tutor · exams · feedback · capabilities · skills · kb · flashcards ·        │
│  phase4_admin · phase5 · phase5_admin · phase6 · phase6_admin ·              │
│  podcast · podcast_admin (+ rbac_deps/dependencies)                          │
│                                                                              │
│  خدمات (services/): ai_gateway · capability_runtime · tutor_service ·        │
│  exam_service(+quiz_validator) · retrieval_service(+multi_grade_rag) ·       │
│  ingestion_service · kb_ingestion_service · podcast_service(+heartbeat) ·    │
│  flashcard_service(+sm2+anki_export) · deep_solve · mistake_bank · mastery · │
│  notebook · living_book · immersive · learner_memory · chat_stream ·         │
│  tts_service · grounding_guard · quota_service · rate_limiter ·              │
│  auth_service · permissions · admin_user_service · upload_guard · …          │
│                                                                              │
│  لایهٔ مدل (models/): ۵۴ جدول ORM · کلیدها: core/crypto.py (Fernet)           │
│                                                                              │
│  فراخوانی مدل: فقط core/llm_client.py (SDK) → فقط services/ai_gateway.py     │
│  (تست معماری test_ai_gateway_isolation.py این را قفل می‌کند)                  │
└───────┬───────────────┬───────────────┬───────────────┬──────────────────────┘
        │               │               │               │
   PostgreSQL      Qdrant          Redis            SMS/Payment
   (Alembic)      (بُرداری،       اختیاری —         providerهای ABC
   مسیر prod      hybrid RAG)     rate-limiter      (demo/kavenegar/
                                  fallback درون-     sms_ir/webhook؛
                                  پردازه‌ای)          demo/zarinpal)
```

**مدل اجرای کارهای پس‌زمینه (دو مسیر متفاوت — تأیید از کد):**

| مسیر | مکانیزم | شواهد |
|---|---|---|
| ingestion کتاب (web KB) | `BackgroundTasks` درون فرآیند uvicorn + جدول `kb_ingestion_jobs` + endpointهای cancel/reindex | `app/api/kb.py:13,39` · `app/api/admin.py:17,1068,2514` · `kb_ingestion_service.py:148` |
| پادکست | پردازش درون‌پردازه‌ای + **worker مستقل** `backend/scripts/podcast_worker.py` + heartbeat (آستانهٔ ۹۰۰ ثانیه) + بازیابی startup | `podcast_service.py:13-16,69,742,1099` · `main.py:26,35-54` — کامنت صریح: «FastAPI BackgroundTasks alone are not trusted for this» |

---

## ۳. موجودی بک‌اند

### ۳.۱ API — شمارش واقعی از اپ ساخته‌شده

با import واقعی `app.main` شمارش شد (اسکریپت inventory؛ FastAPI 0.128 مسیرها را در `_IncludedRouter` نگه می‌دارد و از `original_router` خوانده شد):

| کمیت | مقدار |
|---|---|
| کل عملیات HTTP | **۲۰۶** |
| عملیات زیر `/api/v1/admin` | **۶۵** |
| guarded با `require_admin` | ۶۲ |
| عمداً عمومی | ۳ (`/admin/auth/login`، `/admin/auth/logout`، `/admin/auth/session`) |
| عملیات ادمین بدون guard | **۰** |

گروه‌بندی مسیرهای اصلی (همه با `require_student` مگر اینکه خلاف آن ذکر شود):

| دامنه | مسیرها (نمونهٔ کامل در خروجی inventory) |
|---|---|
| auth (عمومی) | `request-otp`، `verify-otp`، `register/{request-otp,verify-otp,complete}`، `login`، `password/{change,recover/*}`، `csrf`، `me (GET عمومی‌خوان، PUT student)`، `logout` |
| account | profile، avatar، `phone/request-otp`، `phone/verify`، preferences، storage/files، sessions (حذف/revoke-others)، search |
| tutor | `ask`، `ask-image`، `ask-audio`، `stream` (SSE)، sessions CRUD + `search` + `trash` + `restore` + `permanent` |
| exams | `POST/GET ""`، `GET /{id}`، `POST /{id}/submit` — پاسخ قبل از submission بدون `correct_option`/`explanation` (`exam_service.public_exam`) |
| curriculum | grades، majors، branches، fields، cycles، subjects، academic-years، books، tree، search — همهٔ مسیرهای دانش‌آموزی `Book.status == ready` را الزامی می‌کنند |
| immersive / living-book | `immersive/books/{id}` + pages + page-image + assist · `living-book/{book_id}/chapters/{n}` |
| flashcards | decks/cards CRUD، generate، due، review، study-sessions (فعال/پیشرفت/answer/shuffle)، export anki، capability-gate با `require_flashcards_enabled` |
| mistakes | `GET /mistakes`، `practice-set`، `{id}/answer`، `{id}/flashcard` |
| deep-solve | sessions CRUD + `actions` (hint1 → hint2 → step → full) |
| mastery | `books/{id}`، `objectives`، `evidence` + تنظیمات/override ادمین |
| notebook | CRUD نوت‌بوک/بلوک + `inline/{propose,accept,reject}` + `export.md` |
| podcasts | `POST/GET ""`، config، `{id}`، حذف — ادمین: episodes/stats |
| capabilities/skills | `capabilities/me` (get_current_user) + CRUD ادمین؛ skills CRUD + `rollback` + `test` |
| feedback | `POST /feedback/flag` — داخل هندلر `get_optional_user` + 401/403 دستی |
| admin (۶۵ عملیات) | providers، routes، quotas(+features)، audit-logs(+summary/detail/flag)، kb (upload/ingest/jobs/cancel/benchmark/figures)، users (لیست/ایجاد/PATCH/role/activation/password/sessions/credits/audit/memory/mistakes/mastery/deep-solve/quiz-validation)، books legacy، billing/plans، settings، preferences، overview، action-logs، chat-sessions، concept-links، phase6 (living-book/audio-cache) |

### ۳.۲ مدل‌های داده — ۵۴ جدول

`grades, majors, books, book_pages, book_curriculum_links, education_cycles, education_branches, fields_of_study, academic_years, subjects, curriculum_units, learning_objectives, objective_prerequisites, book_page_objectives, learning_evidence` (محتوا) · `users, otp_codes, user_sessions, user_files, plans, billing_settings, payment_transactions, token_usage_logs` (هویت/صورت‌حساب) · `ai_providers, feature_model_routes, user_quotas, ai_audit_logs, admin_action_logs` (حکمرانی) · `capabilities, skills, skill_versions, kb_ingestion_jobs, source_figures, concept_links` (قابلیت/KB) · `chat_sessions, exam_sessions` (گفت‌وگو/آزمون) · `flashcard_decks, flashcards, flashcard_reviews, flashcard_study_sessions` (فلش‌کارت) · `learner_memories, mistake_bank_items, deep_solve_sessions, mastery_chapter_progress, mastery_book_settings, quiz_validation_logs` (یادگیری) · `notebooks, notebook_blocks, living_book_cache, audio_cache` (فاز ۶) · `podcast_episodes, podcast_segments, podcast_feedbacks, podcast_questions` (پادکست).

### ۳.۳ زنجیرهٔ Alembic — ۲۳ revision، یک head

- **head:** `d0e1f2a3b4c5` (podcast_episodes). شمارش خودکار: بدون revision تکراری، فقط یک head.
- **شاخه/merge:** از `f2a3b4c5d6e7` دو شاخه (`a1b2c3d4e5f6` فاز ۵ و `f6a7b8c9d0e1` هستهٔ curriculum) که در `d1e2f3a4b5c6` با دو والد (`d4e5f6a7b8c9`, `f6a7b8c9d0e1`) ادغام شده‌اند.
- ⚠️ **نام فایل گمراه‌کننده:** `a1b2c3d4e5f6_curriculum_unit_branch_scope.py` در واقع revision آن `d1e2f3a4b5c6` است.
- ⚠️ **شکست SQLite (یافتهٔ این فاز):** روی یک SQLite خالیِ تازه، `alembic upgrade head` تا `e2f3a4b5c6d7` بالا می‌آید و در `f3a4b5c6d7e8_book_scoped_learning_evidence` با `NotImplementedError: No support for ALTER of constraints in SQLite dialect` می‌شکند (drop_constraint بدون batch mode). مسیر demo به Alembic وابسته نیست (`create_all`) و مسیر production فرضش PostgreSQL است؛ اما هر محیط غیر-demo مبتنی بر SQLite با این زنجیره قابل‌راه‌اندازی نیست. روی PostgreSQLِ واقعی فقط تا `d4e5f6a7b8c9` (RELEASE_READINESS) و `b7c1d2e3f4a5` (HOTFIX) سند شده؛ revisionهای بعدی (`d1e2f3a4b5c6` تا `d0e1f2a3b4c5`) در این محیط قابل‌راستی‌آزمایی نبود (بدون PostgreSQL).

### ۳.۴ اسکریپت‌ها

`backend/scripts/`: `ingest_book.py`، `index_book.py`، `test_ingest.py` (A/B مدل، pytest آن را جمع نمی‌کند)، `test_llm.py`، `verify_ai_stack.py`، **`podcast_worker.py` (worker مستقل)** · ریشه: `scripts/run-live-demo.sh`.

---

## ۴. موجودی فرانت‌اند (Next.js 16، RTL، App Router)

### ۴.۱ routeها — از خروجی واقعی `next build` (۲۳ مسیر)

| مسیر | نوع | جزء |
|---|---|---|
| `/` | static | `StudentApp.tsx` (۲٬۵۸۵ خط) — کل کلاس دانش‌آموز: انتخاب پایه/رشته/کتاب، چت، تصویر، صدا، آزمون، تاریخچه |
| `/admin` | static | پنل ادمین — تک‌صفحه با تب‌ها + `AdminSideNav` (۵ دسته، drawer موبایل) |
| `/admin/providers` · `/admin/observability` · `/admin/roles` | static | پنل‌های فاز ۱ (`AdminGate` محافظ ورود) |
| `/admin/users/[id]` | dynamic | جزئیات کاربر (`AdminUserDetailPanel`/`AdminUserDetailBody`) |
| `/flashcards` · `/mistakes` · `/mastery` · `/deep-solve` · `/notebook` · `/living-book` · `/podcast` | static | صفحات feature دانش‌آموز — همگی از سایدبار `StudentApp` لینک دارند؛ لینک `/podcast` و بخشی از آیتم‌ها با `capabilityMenuEnabled(...)` از `/api/v1/capabilities/me` gate می‌شوند |
| `/study/[bookId]` | dynamic | خوانندهٔ عمیق (`ImmersiveReaderPage`) — **تنها ورودی فعلی لینک «مطالعهٔ کتاب» در `MasteryWorkspace` است** (gap قابل‌کشف بودن) |
| `/account/*` (۸ مسیر) | static | پوستهٔ تنظیمات، پروفایل، help، upgrade |

### ۴.۲ اجزای کلیدی

- **auth در کلاینت:** `AppProvider.tsx` — توکن در `sessionStorage["iran_tutor_user_token"]`، ارسال با `Authorization: Bearer` + `X-User-Token`؛ رویداد `darsyar:session-expired` → بازگشایی `AuthFlowModal` با پیام فارسی.
- **AJAX:** `lib/apiClient.ts` — نرمال‌سازی خطا (ApiError taxonomy فارسی)، هدر CSRF (`iran_tutor_csrf` + `X-CSRF-Token` با fallback به `/auth/csrf`)، dedupe درخواست هم‌زمان.
- **رندر محتوا:** `MathContent`/`lib/math.ts` (KaTeX LTR)، `MermaidDiagram`، `SvgDiagram` + `lib/safeVisual.ts` (DOMPurify)، `LearningBlockRenderer`.
- **UI polish:** فونت Vazirmatn باندل‌شده، توکن‌های CSS، focus-visible، reduced-motion، touch 44px، toasts (`ToastHost`)، lightbox (`ImageLightbox`/`FigureThumb`).

---

## ۵. baseline تست‌ها (خروجی واقعی)

| gate | فرمان | نتیجهٔ واقعی |
|---|---|---|
| Backend | `cd backend && .venv/bin/python -m pytest -q tests` | ✅ **۴۶۸ passed، ۱ skipped، ۲ warnings** در ۱۹۶.۴۲s (۴۰ ماژول تست) |
| Frontend unit | `cd frontend && npm test` (vitest run) | ✅ **۵ فایل، ۳۹/۳۹ passed** در ۸.۴۷s (apiClient 10، AuthFlowModal 8، AdminUsersPanel 8، FlashcardsWorkspace 7، PodcastWorkspace 6) |
| Frontend lint | `cd frontend && npm run lint` | ❌ **exit 1 — ۱۲ خطا + ۲ هشدار** (همهٔ خطاها `react-hooks/set-state-in-effect`؛ فایل‌ها: `StudentApp.tsx`(۲)، `MistakeBankWorkspace.tsx`، `ImmersiveReader.tsx`، `ChatRecycleBin.tsx`، `BookGradePicker.tsx`، `AuthFlowModal.tsx`، `AdminUsersPanel.tsx`؛ هشدارها: exhaustive-deps در `StudentApp.tsx:937,1244`) |
| Frontend build | `cd frontend && npm run build` | ✅ Compiled successfully (18.3s) — **۲۳ مسیر** (۲۱ static + ۲ dynamic) |
| Alembic (SQLite تازه) | `alembic upgrade head` روی `/tmp/.../check.sqlite3` | ❌ تا `e2f3a4b5c6d7` بالا می‌رود؛ در `f3a4b5c6d7e8` می‌شکند (بند ۳.۳) |
| Alembic (PostgreSQL) | — | **اجرا نشد** — PostgreSQL در سندباکس در دسترس نیست (بند ۵ گزارش فاز) |

> skip واحد: `tests/test_phase4_postgres_smoke.py` — `set PHASE4_PG_URL to run the PostgreSQL smoke test` (طراحی‌شده؛ نیاز به PostgreSQL واقعی دارد و در teardown جدول‌ها را drop می‌کند — هرگز به DB واقعی اشاره نشود).

---

## ۶. راستی‌آزمایی رفتارهای حساس (از کد/تست، نه حدس)

| ادعا | حکم از کد | شواهد |
|---|---|---|
| ورود OTP | ✅ موجود | `api/auth.py:155,185` + variantهای register/recover؛ سقف/انقضا/hash کد |
| رمز عبور | ✅ موجود | `core/passwords.py` (Argon2id، rehash، blocklist)؛ `/auth/login`، `/password/change`، `/password/recover/*`؛ چرخش/ابطال نشست |
| کوکی نشست دانش‌آموز | ✅ موجود | `auth_billing_service.USER_COOKIE_NAME="iran_tutor_user"` + `user_sessions` (nonce قابل‌ابطال)؛ fallback `X-User-Token`/Bearer |
| ذخیرهٔ توکن در کلاینت | ✅ موجود | `AppProvider.tsx:32-49` (sessionStorage) |
| CSRF | ✅ موجود | `core/csrf.py` (سه حالت on/strict/off، double-submit `iran_tutor_csrf`) + middleware در `main.py:95-106` + هدر در `apiClient.ts` |
| ماتریس نقش | ✅ موجود | `services/permissions.py` — `student < guardian < teacher < moderator < admin < super_admin`، محافظت از آخرین super_admin، `ASSIGNABLE/MAINTAINABLE_ROLES` |
| auth legacy ادمین | ✅ حفظ‌شده | `api/rbac_deps.py:8` — کوکی `iran_tutor_admin`/`X-Admin-Token`/Bearer با رمز مشترک **یا** نشست کاربر با `role=admin`؛ 401/403 تفکیک‌شده؛ تست `test_admin_routes_reject_anonymous_and_students` |
| مسیرهای ادمین | ✅ همه guarded | ۶۵ عملیات ادمین؛ فقط ۳ مسیر auth عمداً عمومی؛ تست `test_every_admin_operation_carries_require_admin` |
| `StudentApp.tsx` و صفحات feature | ✅ موجود | بند ۴.۱ — ۸ صفحهٔ feature + gate قابلیت |
| worker پادکست/heartbeat/recovery | ✅ موجود | بند ۲ — worker مستقل + heartbeat 900s + بازیابی startup؛ تست `test_phase9_podcast.py` |
| ingestion کتاب با BackgroundTasks | ✅ موجود | بند ۲ — `api/kb.py` + `kb_ingestion_jobs` + cancel |
| دروازهٔ AI مرکزی | ✅ موجود | `ai_gateway.py` (۹۹۰ خط؛ ۸ تابع شامل stream/TTS/probe)؛ تنها import SDK در `llm_client.py`؛ httpx خام فقط probe Qdrant در `retrieval_service.py:1120-1141` و SMS/Payment پشت ABC؛ تست معماری `test_ai_gateway_isolation.py` (۵ سنجه) |
| auto-publish کتاب | ✅ موجود | `curriculum_access.is_student_visible_book` = فقط `status==ready`؛ `catalog_status` legacy وجود دارد اما در visibility استفاده نمی‌شود (`test_visibility_helper_ignores_legacy_catalog_columns`)؛ انتقال خودکار به ready پس از پردازش (`ingestion_service.py:682`، `kb_ingestion_service.py:220`)؛ `api/curriculum.py:281,382,399` |
| فیلتر `BookPage.status` در retrieval | ✅ موجود | `retrieval_service.py` در ۷ نقطه `status == PageStatus.done`؛ `multi_grade_rag.py:160,222,335,365` + `Book.status==ready` |
| کلید آزمون برای client | ✅ محافظت‌شده | `exam_service.public_exam` — قبل از submission بدون `correct_option`/`explanation`؛ کارنامه فقط پس از submitted |

---

## ۷. فایل‌های حجیم و مرزهای پیشنهادی استخراج تدریجی

| فایل | خط | مرز استخراج پیشنهادی (بدون تغییر رفتار) |
|---|---:|---|
| `backend/app/api/admin.py` | ۳٬۵۹۶ | جدا کردن books/KB، billing/plans، settings/testها، overview به routerهای دامنه‌محور؛ guard مشترک حفظ شود |
| `frontend/app/admin/page.tsx` | ۳٬۵۲۳ | جداسازی تب books/plans/users/integrations/appearance به کامپوننت‌های فایل‌مستقل + ناوبری URL |
| `frontend/components/StudentApp.tsx` | ۲٬۵۸۵ | استخراج سایدبار/ناوبری، runner آزمون، بخش گفت‌وگو به hook/component |
| `backend/app/services/podcast_service.py` | ۱٬۲۵۲ | جداسازی state-machine اپیزود و worker loop |
| `backend/app/services/retrieval_service.py` | ۱٬۱۸۰ | جداسازی qdrant/pgvector adapters و fusion |
| `backend/app/services/flashcard_service.py` | ۱٬۰۹۸ | جداسازی generation از scheduling/review |
| `backend/app/services/admin_user_service.py` | ۱٬۰۸۷ | جداسازی sessions/credits/audit از CRUD |
| `frontend/components/FlashcardsWorkspace.tsx` | ۱٬۶۹۲ | جداسازی study-session player از فرم generate |

قاعدهٔ فازهای بعد: استخراج تدریجی component/hook/service با تست محافظ، بدون تغییر قرارداد API.

---

## ۸. تناقض‌های مستندات با کد (خروجی بند ۴ خواسته‌شده)

| # | سند | ادعا | واقعیت کد/اجرا | اقدام پیشنهادی در فازهای بعد |
|---|---|---|---|---|
| ۱ | `README.md:7` | «APIهای ادمین و معلم هنوز احراز هویت ندارند… فقط برای توسعهٔ محلی» | خط ۲۳۰ خود README و کد خلافش را می‌گویند: ۶۲ عملیات ادمین با `require_admin`، مسیرهای دانش‌آموزی با `require_student`؛ تست governance این را قفل کرده | اصلاح فوری متن امنیتی README (بند گمراه‌کنندهٔ خطرناک) |
| ۲ | `docs/RELEASE_READINESS.md` | ۳۰۸/۳۰۹ تست، head = `d4e5f6a7b8c9` | اکنون ۴۶۸+۱ تست و head = `d0e1f2a3b4c5` (۲۳ revision) | مهر «سند تاریخی فاز ۷» + افزودن سند وضعیت جاری |
| ۳ | `docs/HOTFIX_AUTH_ADMIN_AUDIT_20261122.md` §9 | `npm run lint` → 0 errors، ۱۴ warning | اکنون exit 1 با ۱۲ خطا/۲ هشدار (eslint 9.39.5 قواعد تازه‌تر فعال کرده) | سیاست lint در فاز ۱: اصلاح ۷ فایل یا تنظیم قانون؛ تصمیم مالک |
| ۴ | `docs/UI_POLISH_REPORT.md` | «۲ خطا، هر دو پیش‌موجود» | اکنون ۱۲ خطا در ۷ فایل | به‌روزرسانی یا مهر تاریخی |
| ۵ | `docs/PHASE0_INVENTORY.md` §2 | «No separate worker/queue process exists» | `scripts/podcast_worker.py` (worker مستقل) + جدول jobs + cancel موجود است | به‌روزرسانی؛ workerها در ماتریس وضعیت ثبت شدند |
| ۶ | `docs/PHASE0_INVENTORY.md` §11 | «frontend has zero tests» | ۳۹ تست Vitest در ۵ فایل | به‌روزرسانی |
| ۷ | `docs/PHASE0_INVENTORY.md` §11 | «no CI workflow (.github/ does not exist)» | `.github/workflows/ci.yml` موجود است (backend+frontend jobs) | به‌روزرسانی |
| ۸ | `docs/HOTFIX…` §3 | «۲۰ revision، head `a4b5c6d7e8f9`» | ۲۳ revision، head `d0e1f2a3b4c5` | به‌روزرسانی |
| ۹ | نام فایل migration | — | `a1b2c3d4e5f6_curriculum_unit_branch_scope.py` با revision واقعی `d1e2f3a4b5c6` گمراه‌کننده است | تغییر نام فایل (فقط در فاز مجاز migration) |
| ۱۰ | `docs/RELEASE_READINESS.md` §1 | alembic روی SQLite فقط «dialect-only drift» دارد | روی SQLite **تازه**، `upgrade head` در `f3a4b5c6d7e8` کامل شکست می‌خورد | ثبت محدودیت «SQLite فقط مسیر demo/create_all» در runbook |
| ۱۱ | `.kilocode/rules/architecture.md` | فاز ۶ = «SMS OTP auth … نه بعداً»؛ «do not build auth yet» | auth کامل پیاده شده (OTP+password+RBAC+CSRF)؛ سند در بخش فازها عقب مانده است | مهر تاریخی روی بخش Phases؛ قواعد دامنه (پایه/رشته) همچنان مرجع است |

---

## ۹. ابهام‌ها/Blockerهای فهرست‌شده پیش از فاز ۱

1. **دروازهٔ lint قرمز است** (۱۲ خطا) — سیاست (اصلاح کد یا تنظیم قانون) نیاز به تصمیم مالک دارد؛ تکرار در گزارش فاز.
2. **زنجیرهٔ migration روی PostgreSQL از `d4e5f6a7b8c9` به بعد در این محیط راستی‌آزمایی نشد** — پیش از هر تغییر schema در فازهای بعد، `alembic upgrade head` + `alembic check` روی PostgreSQL اختصاصی خالی اجرا شود (هرگز روی DB واقعی).
3. **پشتیبانی Alembic روی SQLite از `f3a4b5c6d7e8` به بعد ناممکن است** — تصمیم مالک: نیازمندی است یا نه (production = PostgreSQL).
4. **README:7 متن امنیتی غلط/کهنه دارد** — باید در نخستین PR مستنداتی اصلاح شود.
5. **`/study/[bookId]` تنها از مسیر Mastery قابل‌دسترس است** — تصمیم UX برای فاز بازطراحی UI.
6. **آرشیو بدون `.git` است** — فازهای بعدی باید در checkout واقعی مالک با git اجرا شوند تا گزارش‌ها به commit ارجاع دهند.
7. **سرویس‌های واقعی (PG/Qdrant/Redis) و کیفیت مدل واقعی در این baseline آزموده نشدند** — ادعاهای عملکرد مدل/OCR همچنان «فقط مستند/نیازمند اعتبارسنجی با سرویس واقعی» است.

---

## ۱۰. به‌روزرسانی فاز ۰۰-A (۲۰۲۶-۱۱-۲۳) — وضعیت blockerهای بند ۹

| Blocker | وضعیت پس از ۰۰-A | مرجع |
|---|---|---|
| ۱ (lint قرمز) | ✅ رفع — ۰ خطا / ۰ هشدار، بدون غیرفعال‌سازی قانون؛ باگ تایمر فوکوس مودال هم که تست را flaky می‌کرد اصلاح شد | گزارش ۰۰-A بند ۲ |
| ۲ (PG از `d4e5f6a7b8c9` به بعد) | ✅ رفع — کل زنجیره روی PostgreSQL مستقل واقعی تا head بالا رفت؛ drift `flashcard_study_sessions.user_id` کشف و با migration `e1f2a3b4c5d6` اصلاح شد؛ `alembic check` تمیز؛ smoke فاز ۴ روی PG واقعی پاس شد | گزارش ۰۰-A بند ۴ |
| ۳ (Alembic روی SQLite) | ✅ تصمیم گرفته شد — SQLite رسماً demo-only؛ محدودیت رسمی مستند (D-002)؛ migration قدیمی تغییر نکرد | Decision Log D-002 |
| ۴ (README:7) | ✅ اصلاح شد (خط ۵ و ۷) | گزارش ۰۰-A بند ۲ |
| ۵ (`/study/[bookId]`) | ✅ تصمیم ثبت شد — لینک مطالعهٔ مستقیم از کارت کتاب در Mastery، نقطهٔ ورود رسمی؛ بدون تغییر UI | Decision Log D-001 |
| ۶ (نبود `.git`) | ⏳ ساختاری — patch استاندارد برای checkout واقعی مالک تولید شد (`download/iran-tutor-phase00-00a.patch`)؛ مالک باید در checkout واقعی بازبینی/commit کند | گزارش ۰۰-A بند ۶ |
| ۷ (سرویس‌های واقعی) | ⚠️ تا حدی — PostgreSQL واقعی (embedded) تأمین و migration + smoke روی آن اجرا شد؛ Qdrant/Redis/کیفیت مدل واقعی همچنان «نیازمند اعتبارسنجی» است | گزارش ۰۰-A بند ۵ |
