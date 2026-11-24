# REDESIGN — ماتریس وضعیت قابلیت‌ها (فاز ۰۰)

> **تاریخ:** ۲۰۲۶-۱۱-۲۳ · **منبع:** کد جاری + اجرای واقعی تست‌ها (نه مستندات)
> ستون «وضعیت اعتبارسنجی» سه مقدار دارد: **تأیید از کد+تست** (کد و تست محافظ هر دو بررسی/اجرا شدند)، **تأیید از کد** (کد بررسی شد؛ تست اختصاصی اجرا نشد یا شبیه‌سازی است)، **نیازمند اعتبارسنجی واقعی** (نیازمند سرویس/دستگاه/مدل واقعی).
> ستون «اقدام پیشنهادی» فقط پیشنهاد است و تصمیم با مالک پروژه است.

## الف) احراز هویت، نشست و دسترسی

| قابلیت | موجود در کد | API موجود | UI موجود | تست موجود | وضعیت اعتبارسنجی | اقدام پیشنهادی |
|---|---|---|---|---|---|---|
| ورود OTP (legacy) | `api/auth.py:155,185` · `services/auth_service.py` · `sms_provider.py` (demo/kavenegar/sms_ir/webhook) | `POST /auth/request-otp` · `POST /auth/verify-otp` | `AuthFlowModal` (ورود با کد پیامکی) | `test_user_auth_admin.py` (انقضا/سقف تلاش/isolation purpose/cooldown) | تأیید از کد+تست | حفظ؛ ارسال SMS واقعی نیازمند سرویس |
| ثبت‌نام (موبایل → OTP → رمز) | `api/auth.py:352-396` | `POST /auth/register/{request-otp,verify-otp,complete}` | `AuthFlowModal` — ماشین‌حالت ثبت‌نام | `test_user_auth_admin.py` (دوباره‌ثبت شماره، handshake) | تأیید از کد+تست | حفظ |
| ورود با رمز | `core/passwords.py` (Argon2id، rehash، blocklist) · `auth_service.password_login` | `POST /auth/login` | `AuthFlowModal` | `test_user_auth_admin.py` (موفق/ناموفق/چرخش نشست/نرخ) | تأیید از کد+تست | حفظ |
| بازیابی رمز | `auth_service.reset_password` · ابطال همهٔ نشست‌ها | `POST /auth/password/recover/{request-otp,verify-otp,complete}` · `POST /auth/password/change` | `AuthFlowModal` («رمز عبورم را فراموش کرده‌ام») | `test_user_auth_admin.py` | تأیید از کد+تست | حفظ |
| کوکی نشست دانش‌آموز | `auth_billing_service.USER_COOKIE_NAME="iran_tutor_user"` · `core/signing.py` (HMAC) · جدول `user_sessions` (nonce قابل‌ابطال) | همهٔ مسیرهای `require_student` | کوکی HttpOnly + fallback `X-User-Token`/Bearer | `test_user_auth_admin.py` · `test_account_and_settings.py` | تأیید از کد+تست | حفظ؛ سیاست چرخش توکن در فازهای بعد |
| ذخیرهٔ توکن در کلاینت | `AppProvider.tsx:32-49` (`sessionStorage["iran_tutor_user_token"]`) | — | ارسال `Bearer` + `X-User-Token` در `apiClient` | `tests/apiClient.test.ts` (10) · `AuthFlowModal.test.tsx` | تأیید از کد+تست | حفظ |
| CSRF | `core/csrf.py` (on/strict/off، double-submit `iran_tutor_csrf`) · `main.py:95-106` | `GET /auth/csrf` | `apiClient.ts` هدر `X-CSRF-Token` + memo | `test_user_auth_admin.py` (حالت‌های strict/default) | تأیید از کد+تست | حفظ؛ مستندسازی وابستگی به Origin/Referer |
| ماتریس نقش | `services/permissions.py` — `student < guardian < teacher < moderator < admin < super_admin`، آخرین super_admin محافظت‌شده | `GET /admin/users/roles` · `PUT /admin/users/{id}/role` (reauth) | `AdminUsersPanel` (تغییر نقش با رمز خود ادمین) | `test_user_auth_admin.py` (escalation blocked، last-super_admin) | تأیید از کد+تست | حفظ |
| auth legacy ادمین | `api/rbac_deps.py:8` — کوکی `iran_tutor_admin`/`X-Admin-Token`/Bearer با رمز مشترک **یا** نشست `role=admin` | تمام `/admin/*` | `AdminGate` (لاگین پنل) | `test_phase1_governance.py` (401/403/200) | تأیید از کد+تست | در فازهای بعد مسیر واقعی `super_admin` جایگزین رمز مشترک شود (ریسک مستند در HOTFIX §11) |
| Dev seed | `db/dev_seed.py` (idempotent، refused در production) | — | — | `test_user_auth_admin.py` (idempotency، production refusal) | تأیید از کد+تست | حفظ (فقط محیط dev) |
| production guard | `core/production_guard.py` (APP_ENV، رمز ضعیف → RuntimeError) | — | — | `test_phase7_followup.py` (۷ سنجه) | تأیید از کد+تست | حفظ |

## ب) مسیرهای ادمین

| قابلیت | موجود در کد | API موجود | UI موجود | تست موجود | وضعیت اعتبارسنجی | اقدام پیشنهادی |
|---|---|---|---|---|---|---|
| `/admin` (پوسته) | `frontend/app/admin/page.tsx` (۳٬۵۲۳ ل) + `AdminSideNav.tsx` + `AdminGate.tsx` | `POST/GET /admin/auth/*` (۳ مسیر عمومی) | تب‌های overview/books/plans/users/integrations/appearance + ۵ دستهٔ ناوبری + drawer موبایل | `test_admin_api.py` (11) · `test_admin_control_center.py` | تأیید از کد+تست | استخراج تدریجی صفحات از تک‌فایل ۳٬۵۲۳ خطی |
| `/admin/providers` | `components/AdminProvidersPanel.tsx` (۷۸۰ ل) · `api/admin.py` + `ai_provider_service.py` · vault رمزنگاری `core/crypto.py` | `GET/POST/PUT/DELETE /admin/providers` · `POST /admin/providers/{id}/test` · `GET/PUT/DELETE /admin/routes` | CRUD با کلید ماسک‌شده، chip قابلیت، تست اتصال زنده، ماتریس مسیریابی per-feature | `test_phase1_governance.py` (5,21) · `test_provider_routing_failover.py` | تأیید از کد+تست | حفظ |
| `/admin/observability` | `components/AdminObservabilityPanel.tsx` (۶۱۶ ل) · جدول `ai_audit_logs` | `GET /admin/audit-logs(/summary/{id})` · `POST /admin/audit-logs/{id}/flag` | کارت‌های خلاصه، جدول فیلترپذیر، drawer کامل prompt/response/citation/token/cost | `test_phase1_governance.py` (7,8,9,15,18,19) · جاروی canary `test_no_admin_response_ever_contains_a_plaintext_secret` | تأیید از کد+تست | حفظ |
| `/admin/roles` | `components/AdminRolesQuotasPanel.tsx` · `quota_service.py` (per-feature overrides) | `GET/PUT /admin/quotas` · `PUT/DELETE /admin/quotas/features/{key}` | فرم سیاست سهمیه + ویرایش نقش/پایه/رشته/فعال بودن کاربر | `test_phase1_governance.py` (11,12,17) · `test_phase7_followup.py` (per-capability) | تأیید از کد+تست | حفظ |
| `/admin/users/[id]` | `frontend/app/admin/users/[id]/page.tsx` + `AdminUserDetailPanel/Body.tsx` · `admin_user_service.py` (۱٬۰۸۷ ل) | `GET/PATCH /admin/users/{id}` · role/activation/password/sessions/credits/audit/memory/mistakes/mastery/deep-solve/quiz-validation | پروفایل، نقش، رمز، نشست‌ها، اعتبار، تاریخچه audit، memory L1/L2/L3 | `test_user_auth_admin.py` · `test_phase4/5_admin` | تأیید از کد+تست | حفظ |
| مدیریت کاربران (لیست) | `AdminUsersPanel.tsx` (۱٬۳۲۲ ل) | `GET /admin/users` (pagination/filters/role counts) · `POST /admin/users` · `DELETE` (soft) | جست‌وجو + فیلتر role/status/plan در URL + KPI + dialog تأیید + reauth | `test_user_auth_admin.py` (فیلتر/صفحه‌بندی/نشست) | تأیید از کد+تست | حفظ |
| KB / ingestion ادمین | `api/kb.py` + `kb_ingestion_service.py` · `AdminKbPanel.tsx` | `POST /admin/kb/books/{id}/ingest` · jobs (`GET/cancel`) · reindex-chapter/page · benchmark · figures (+extract) | پنل KB با پیشرفت شغل، تصاویر figures | `test_phase2_capabilities_kb.py` | تأیید از کد+تست | حفظ |

## ج) صفحات دانش‌آموز

| قابلیت | موجود در کد | API موجود | UI موجود | تست موجود | وضعیت اعتبارسنجی | اقدام پیشنهادی |
|---|---|---|---|---|---|---|
| `StudentApp.tsx` | `components/StudentApp.tsx` (۲٬۵۸۵ ل) — کل کلاس: انتخاب درسی، چت، تصویر/صدا، آزمون زمان‌دار، تاریخچه | مصرف‌کنندهٔ tutor/exams/curriculum | سایدبار با لینک صفحات feature (بخشی با gate قابلیت) + dark mode + GlobalSearch | پوشش غیرمستقیم با `test_tutor_api.py` و… | تأیید از کد | استخراج تدریجی به hook/component با تست |
| `/flashcards` | `FlashcardsWorkspace.tsx` (۱٬۶۹۲ ل) · `flashcard_service.py` (۱٬۰۹۸ ل) + `sm2.py` + `anki_export.py` + `flashcard_sources.py` | decks/cards CRUD · generate · due · review · study-sessions (active/progress/answer/shuffle) · `export/anki` | deck list با Due/progress، مودال generate (کتاب/چت/اشتباه)، فلش‌کارت با KaTeX و ۴ دکمهٔ SM-2، export | `test_phase3_flashcards.py` · `test_phase8_flashcard_study.py` · UI: `FlashcardsWorkspace.test.tsx` (7) | تأیید از کد+تست (SM-2 با تست واحد) | حفظ؛ کیفیت تولید با مدل واقعی نیازمند اعتبارسنجی |
| `/podcast` | `PodcastWorkspace.tsx` (۱٬۰۵۹ ل) + `PodcastPlayerProvider.tsx` · `podcast_service.py` (۱٬۲۵۲ ل) | `POST/GET /podcasts` · config · `{id}` · حذف · ادمین episodes/stats | فرم تولید (منبع/قالب/طول) + player + وضعیت job | `test_phase9_podcast.py` · UI: `PodcastWorkspace.test.tsx` (6) | تأیید از کد+تست (TTS واقعی نیازمند سرویس) | حفظ |
| `/study/[bookId]` | `ImmersiveReaderPage.tsx` + `ImmersiveReader.tsx` · `immersive_service.py` · `FigureThumb` (تصویر figures از endpoint دانش‌آموز) | `GET /immersive/books/{id}` · `pages/{n}`(+image) · `assist` | نمای دوستونه RTL، تب موبایل «صفحهٔ کتاب \| گفت‌وگو»، لایت‌باکس شکل‌ها | `test_phase6_rich_study.py` · `test_book_curriculum_scope.py` | تأیید از کد+تست | gap: تنها ورودی ناوبری لینک «مطالعهٔ کتاب» در `/mastery` است |
| `/deep-solve` | `DeepSolveWorkspace.tsx` · `deep_solve_service.py` | `POST/GET /deep-solve/sessions` · `{id}` · `{id}/actions` | stepper: Hint1 → Hint2 → Step → Full (از `available_actions` سرور) | `test_phase5_deep_learning.py` · IDOR: `get_owned` audit‌شده | تأیید از کد+تست | حفظ |
| `/mistakes` | `MistakeBankWorkspace.tsx` · `mistake_bank_service.py` | `GET /mistakes` · `practice-set` · `{id}/answer` · `{id}/flashcard` | بانک اشتباه با وضعیت unresolved/practiced/mastered + ارسال به فلش‌کارت | `test_phase5_deep_learning.py` (ثبت خودکار از آزمون) | تأیید از کد+تست | حفظ |
| `/mastery` | `MasteryWorkspace.tsx` · `mastery_service.py` (۷۴۸ ل) | `GET /mastery/books/{id}`(+objectives) · `POST /mastery/evidence` · ادمین settings/override | تایم‌لاین فصل‌ها (mastered/in-progress/locked) + لینک مطالعه | `test_phase5_deep_learning.py` | تأیید از کد+تست | حفظ |
| `/notebook` | `NotebookWorkspace.tsx` · `notebook_service.py` | CRUD نوت‌بوک/بلوک · `inline/{propose,accept,reject}` · `export.md` | workspace بلوکی + diff پذیرش/رد AI + پرینت | `test_phase6_rich_study.py` | تأیید از کد+تست | حفظ |
| `/living-book` | `LivingBookWorkspace.tsx` · `living_book_service.py` + cache | `GET /living-book/{book_id}/chapters/{n}` | خلاصهٔ تعاملی فصل (blocks + mini-quiz + فلش‌کارت) | `test_phase6_rich_study.py` | تأیید از کد+تست | حفظ |
| گفت‌وگو با streaming/سبد بازیافت | `chat_stream.py` + `tutor_turns.py` · `lib/tutorStream.ts` · `ChatRecycleBin.tsx` | `POST /tutor/stream` (SSE) · sessions `search/trash/restore/permanent` | Stop/Regenerate/سرصفحهٔ بازیافت | `test_phase4_memory_rag_streaming.py` | تأیید از کد+تست | حفظ |
| حافظهٔ یادگیرنده L1/L2/L3 | `learner_memory_service.py` + `learner_memory.py` | `GET/PUT/DELETE /admin/users/{id}/memory` | Memory Inspector (کارت‌های لایه‌رنگ) | `test_phase4_memory_rag_streaming.py` | تأیید از کد+تست | حفظ |

## د) کارهای پس‌زمینه، دروازهٔ AI و انتشار

| قابلیت | موجود در کد | API موجود | UI موجود | تست موجود | وضعیت اعتبارسنجی | اقدام پیشنهادی |
|---|---|---|---|---|---|---|
| worker پادکست مستقل | `scripts/podcast_worker.py` | — (poll jobs) | — | `test_phase9_podcast.py` | تأیید از کد+تست (اجرای بلندمدت با سرویس واقعی نیازمند اعتبارسنجی) | مستندسازی استقرار worker در runbook |
| heartbeat/recovery پادکست | `podcast_service.py:69,742,754-765,1099` (STALE_AFTER=900s) · `main.py:26,35-54` (startup sweep) | — | نمایش وضعیت قابل‌تلاش مجدد به دانش‌آموز | `test_phase9_podcast.py` | تأیید از کد+تست | حفظ |
| ingestion کتاب (web) | `api/kb.py` + `kb_ingestion_service.py:148` با `BackgroundTasks` + `kb_ingestion_jobs` (+ مسیر legacy `admin.py:1068,2514`) | ingest/jobs/cancel/reindex | پنل KB با پیشرفت | `test_phase2_capabilities_kb.py` | تأیید از کد+تست | حفظ؛ OCR واقعی نیازمند مدل واقعی |
| دروازهٔ AI مرکزی | `ai_gateway.py` (۹۹۰ ل؛ ۸ تابع: text/json/vision/stt/tts/embed/stream/probe) · تنها import SDK در `core/llm_client.py` (۸۱۸ ل) | مصرف داخلی همهٔ سرویس‌ها | `/admin/providers` (تست اتصال) | `test_ai_gateway_isolation.py` (۵ سنجهٔ معماری + کنترل منفی) · `test_llm_wrappers.py` | تأیید از کد+تست | حفظ؛ هر مسیر جدید اجباری از gateway |
| vault کلید | `core/crypto.py` (Fernet از SECRET_KEY، `enc:v1:`، ماسک) | providers CRUD (`api_key: null`) | ماسک در UI | جاروی canary در `test_phase1_governance.py` | تأیید از کد+تست | حفظ |
| auto-publish کتاب | `curriculum_access.py` (`is_student_visible_book` = فقط `status==ready`) · `ingestion_service.py:682` · `kb_ingestion_service.py:220` · `api/curriculum.py:281,382,399` · `catalog_status` legacy غیرفعال | GETهای دانش‌آموزی فقط `ready` | انتخاب کتاب فقط `ready` | `test_phase10_auto_publish.py` (۱۱ سنجه شامل ingesting/failed غیرقابل‌انتخاب و نادیده‌گرفتن ستون‌های legacy) | تأیید از کد+تست | قانون انتشار خودکار دست‌نخورده بماند |
| فیلتر وضعیت صفحه در RAG | `retrieval_service.py` (۷ نقطهٔ `PageStatus.done`) · `multi_grade_rag.py:365` (+`Book.status==ready`) | — | — | `test_phase10_auto_publish.py` (310,319,353) · `test_retrieval_and_tutor.py` · `test_hybrid_rag.py` | تأیید از کد+تست (Qdrant واقعی نیازمند سرویس؛ مسیر lexical/SQLite پوشش داده شده) | حفظ — `needs_review`/`failed` هرگز وارد retrieval نشوند |
| کلید آزمون مخفی | `exam_service.public_exam` (بدون `correct_option`/`explanation` قبل از submission) | `POST /exams` · `GET /{id}` · `submit` | ExamRunner | `test_exams.py` (11) | تأیید از کد+تست | حفظ |
| سهمیه/نرخ | `quota_service.py` (per-feature override) · `rate_limiter.py` (Redis یا درون‌پردازه‌ای) | اعمال در tutor/exams/quiz · مدیریت `/admin/quotas*` | بخش «سقف مصرف به‌تفکیک قابلیت» | `test_phase1_governance.py` (11-14) · `test_phase7_followup.py` | تأیید از کد+تست (Redis واقعی اجرا نشد — fallback تست شده) | در استقرار multi-worker Redis الزامی شود |
| گزارش خرابی پاسخ | `api/feedback.py` (ownership: `user_id == caller or NULL`) | `POST /feedback/flag` | دکمهٔ گزارش در چت | `test_phase1_governance.py` (16,20) · `test_phase7_followup.py` (403 foreign) | تأیید از کد+تست | حفظ |
| grounding guard | `grounding_guard.py` (book/ready/cross-book/printed page) — فقط flag، هرگز بلاک | — | صف `flagged` در observability | `test_phase7_hardening/followup` | تأیید از کد+تست | حفظ |
| قابلیت‌ها (registry) | `capability_service.py` + `capabilities.py` (model) + `capability_runtime.py` | `GET /capabilities/me` + CRUD ادمین | منوی پویا با `capabilityMenuEnabled` | `test_phase2_capabilities_kb.py` | تأیید از کد+تست | حفظ |
| skills/prompts | `skills.py` (model) + `skill_seed.py` + `api/skills.py` | CRUD + `rollback` + `test` | `AdminSkillsPanel` | `test_phase2_capabilities_kb.py` | تأیید از کد+تست | حفظ |
| TTS / Audio Overview | `tts_service.py` + `speech_via_gateway` + `audio_cache` | endpointهای phase6 + `audio-cache` ادمین | `AudioButton.tsx` | `test_phase6_rich_study.py` | تأیید از کد (صوت واقعی نیازمند سرویس) | اعتبارسنجی با provider واقعی |
| RAG چندپایه (کنکور) | `multi_grade_rag.py` + `concept_links` | مصرف در tutor/konkoor | فیلتر کنکور در UI | `test_phase4_memory_rag_streaming.py` · `test_phase10_auto_publish.py:353` | تأیید از کد+تست | حفظ |
| مسیر fallback ارائه‌دهنده | `ai_gateway._call_provider_candidates` + migration `e2f3a4b5c6d7` | — | — | `test_provider_routing_failover.py` | تأیید از کد+تست | حفظ |

## هـ) شکاف‌ها و موارد «فقط مستند»

| مورد | وضعیت واقعی | اقدام |
|---|---|---|
| کیفیت پاسخ/OCR با مدل واقعی | هیچ baseline مدل واقعی در این فاز اجرا نشد؛ مستندات هم تأیید می‌کنند (`README` بند ۵، `UI_POLISH` بند ۱۲) | اعتبارسنجی جداگانه با provider پیکربندی‌شده (خارج از فازهای بازطراحی) |
| QA مرورگری RTL/KaTeX/Mermaid/پرینت | بدون مرورگر در سندباکس؛ `UI_POLISH` بند ۱۲ نیز open است | QA دستی با چک‌لیست گزارش فاز |
| transcribe واقعی صدا | `ask-audio` وابسته به `SPEECH_TO_TEXT_MODEL`؛ پشتیبانی provider باید جداگانه بررسی شود (`README`) | تست با سرویس واقعی |
| Redis در استقرار واقعی | fallback درون‌پردازه‌ای تست شده؛ Redis واقعی اجرا نشد | فعال‌سازی در production runbook |
| آلِم‌بیک روی PostgreSQL از `d4e5f6a7b8c9` به بعد | در این محیط اجرا نشد (بدون PG)؛ روی SQLite تازه از `f3a4b5c6d7e8` می‌شکند | اجرای `upgrade head + check` روی PG اختصاصی خالی قبل از فاز تغییر schema |
