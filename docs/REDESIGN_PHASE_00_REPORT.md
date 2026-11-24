# گزارش فاز ۰۰ — تثبیت Baseline و موجودی واقعی

> **تاریخ:** ۲۰۲۶-۱۱-۲۳ · **وضعیت نهایی: PASS** (با ریسک‌ها و تصمیم‌های فهرست‌شده در بند ۶)
> **قواعد حاکم:** `00-COMMON-RULES` (قواعد مشترک اجرای فازها) · `.kilocode/rules/architecture.md`
> **سندهای خروجی این فاز:** `REDESIGN_EXECUTION_BASELINE.md` · `REDESIGN_STATUS_MATRIX.md` · همین گزارش

---

## ۱. خلاصهٔ دقیق تغییرات و دلیل

در این فاز **هیچ فایل اجرایی (کد، migration، پیکربندی، اسکریپت) تغییر نکرده است.** تغییرات فقط افزودن سه سند مستنداتی در `docs/` است. دلیل: هدف فاز ۰۰ اثبات وضعیت واقعی این checkout با کد و تست، و فهرست تناقض مستندات، پیش از هر تغییر رفتار است.

کارهای انجام‌شده:

1. ریشهٔ مخزن شناسایی شد (`backend/` + `frontend/` موجود) و هر ۱۰ سند مرتبط خوانده شد (`architecture.md`, `README.md`, `DARSYAR_AGENT_PACK.md`, `RELEASE_READINESS.md`, `UI_POLISH_REPORT.md`, `HOTFIX_AUTH_ADMIN_AUDIT_20261122.md`, `PHASE0_INVENTORY.md`, `PHASE1_AUDIT.md`, `PHASE1_REPORT.md`, راهنمای راه‌اندازی).
2. وضعیت git ثبت شد: **آرشیو zip فهرست `.git` ندارد**؛ در محیط اجرا کل درخت به‌عنوان untracked زیر مخزن والد (`main` @ `ef56c37`) دیده می‌شود. هیچ commit/push/reset انجام نشد و هیچ تغییر محلی‌ای برای پاک‌کردن وجود نداشت.
3. Inventory کامل بک‌اند و فرانت‌اند از import واقعی اپ و خروجی واقعی build استخراج شد: **۲۰۶ عملیات HTTP، ۶۵ عملیات ادمین (۳ مسیر عمداً عمومی، صفر مسیر بدون guard)، ۵۴ جدول ORM، ۲۳ revision Alembic با head یکتای `d0e1f2a3b4c5`، ۲۳ مسیر Next.js**.
4. موارد خواسته‌شده در محدودهٔ فاز راستی‌آزمایی شد (auth کامل، مسیرهای ادمین، صفحات دانش‌آموز، worker پادکست در برابر BackgroundTasks، دروازهٔ AI، auto-publish، فیلتر RAG) — نتایج در `REDESIGN_EXECUTION_BASELINE.md` §۶ و `REDESIGN_STATUS_MATRIX.md`.
5. هر ۴ gate تست خواسته‌شده اجرا شد (بند ۴) و یک آزمایش اضافهٔ زنجیرهٔ migration روی SQLite خالی انجام شد که یک یافتهٔ جدید داد (بند ۴ و ریسک ۳).
6. تناقض مستندات با کد فهرست شد: **۱۱ مورد** در `REDESIGN_EXECUTION_BASELINE.md` §۸.
7. فایل‌های حجیم و مرزهای استخراج تدریجی فهرست شد: `REDESIGN_EXECUTION_BASELINE.md` §۷.

## ۲. فهرست فایل‌های تغییرکرده/جدید و نقش هر فایل

| فایل | وضعیت | نقش |
|---|---|---|
| `docs/REDESIGN_EXECUTION_BASELINE.md` | **جدید** | baseline معماری، موجودی route/API/مدل/Alembic/worker، نتیجهٔ تست‌ها، راستی‌آزمایی رفتارهای حساس، فایل‌های حجیم، تناقض مستندات |
| `docs/REDESIGN_STATUS_MATRIX.md` | **جدید** | ماتریس قابلیت با ستون‌های موجود در کد/API/UI/تست/وضعیت اعتبارسنجی/اقدام پیشنهادی + بخش شکاف‌ها |
| `docs/REDESIGN_PHASE_00_REPORT.md` | **جدید** | همین گزارش — دروازهٔ تحویل فاز |

**فایل‌های کد و migration: بدون هیچ تغییر.** آرتیفکت‌های اجرایی که فقط در محیط اجرا ساخته شدند و توسط `.gitignore` پوشش داده می‌شوند: `backend/.venv/`، `frontend/node_modules/`، `frontend/.next/`. `frontend/next-env.d.ts` با diff با نسخهٔ آرشیو یکسان تأیید شد. دو فایل موقت تست خارج از مخزن (`/tmp`) ساخته و حذف شدند.

**اثر جانبی اجرای تست‌ها و اصلاح آن:** اجرای مجموعهٔ تست باعث بازتولید `backend/storage/demo/sample_physics.pdf` توسط seeder دمو (`app/db/seed.py:247`) و ساخت `backend/storage/tts_cache/` شد. مطابق قاعدهٔ «storage/PDF دست‌نخورده بماند»، این فایل از آرشیو اصلی **بایت‌به‌بایت بازیابی** (با `cmp` تأیید شد) و پوشهٔ cache ساخته‌شده توسط تست حذف شد؛ مقایسهٔ نهایی کل درخت با آرشیو نشان می‌دهد تنها تفاوت، همان ۳ سند جدید `docs/REDESIGN_*.md` است.

## ۳. قابلیت‌های قبلی که حفظ شدند و تست محافظ آن‌ها

چون این فاز read-only بود، «حفظ» با اجرای کل مجموعهٔ رگرسیون اثبات می‌شود: **۴۶۸ تست backend + ۳۹ تست Vitest، هر دو سبز** (بند ۴). مهم‌ترین تست‌های محافظ رفتارهای حساس:

| رفتار محافظت‌شده | تست محافظ |
|---|---|
| فقط `core/llm_client.py` SDK را import می‌کند؛ همهٔ مسیرها از `ai_gateway` | `test_ai_gateway_isolation.py` (۵ سنجهٔ معماری) |
| همهٔ عملیات ادمین guarded (فقط ۳ مسیر auth عمومی) | `test_every_admin_operation_carries_require_admin` |
| هیچ پاسخ ادمین کلید plaintext ندارد | `test_no_admin_response_ever_contains_a_plaintext_secret` (جاروی canary + لاگ) |
| auto-publish و نادیده‌گرفتن ستون‌های legacy در visibility | `test_phase10_auto_publish.py` (۱۱ سنجه) |
| فیلتر `BookPage.status == done` در RAG و scope کتاب | `test_phase10_auto_publish.py` · `test_retrieval_and_tutor.py` · `test_hybrid_rag.py` |
| auth رمز/OTP/ثبت‌نام/بازیابی/RBAC/CSRF/آخرین super_admin | `test_user_auth_admin.py` (۲۱ سنجه) |
| کلید آزمون قبل از submission افشا نمی‌شود | `test_exams.py` |
| SM-2 و study-session فلش‌کارت | `test_phase3_flashcards.py` · `test_phase8_flashcard_study.py` |
| پادکست (heartbeat/recovery/worker) | `test_phase9_podcast.py` |
| streaming/recycle-bin/حافظهٔ L1-L3/RAG چندپایه | `test_phase4_memory_rag_streaming.py` |
| production guard (رمز ضعیف → بوت نشدن) | `test_phase7_followup.py` |
| کلاینت AJAX/auth UI | `tests/apiClient.test.ts` · `AuthFlowModal.test.tsx` · `AdminUsersPanel.test.tsx` · `FlashcardsWorkspace.test.tsx` · `PodcastWorkspace.test.tsx` |

هیچ assertionای تغییر نکرده یا حذف نشده است (هیچ فایل تستی دست نخورده).

## ۴. فرمان‌های دقیق اجراشده و خروجی واقعی

| # | فرمان | خروجی واقعی |
|---|---|---|
| ۱ | `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (backend) | نصب موفق؛ FastAPI 0.128.0 |
| ۲ | `npm ci --no-audit --no-fund` (frontend) | نصب موفق از `package-lock.json` |
| ۳ | `cd backend && .venv/bin/python -m pytest -q tests` | **۴۶۸ passed، ۱ skipped، ۲ warnings** در 196.42s — exit 0. skip: `test_phase4_postgres_smoke.py` (`set PHASE4_PG_URL to run the PostgreSQL smoke test`) |
| ۴ | `cd frontend && npm test` (vitest run) | **۵ فایل / ۳۹ passed، 0 failed** در 8.47s — exit 0 |
| ۵ | `cd frontend && npm run lint` | **exit 1 — ۱۴ مشکل: ۱۲ خطا (`react-hooks/set-state-in-effect`) + ۲ هشدار (`exhaustive-deps`)**. فایل‌های دارای خطا: `StudentApp.tsx`، `MistakeBankWorkspace.tsx`، `ImmersiveReader.tsx`، `ChatRecycleBin.tsx`، `BookGradePicker.tsx`، `AuthFlowModal.tsx`، `AdminUsersPanel.tsx` |
| ۶ | `cd frontend && npm run build` | **Compiled successfully (18.3s) — ۲۳ مسیر** (۲۱ static + `/admin/users/[id]` و `/study/[bookId]` dynamic) — exit 0 |
| ۷ | `alembic upgrade head` روی SQLite خالی تازه در `/tmp` | **شکست در `f3a4b5c6d7e8_book_scoped_learning_evidence`**: `NotImplementedError: No support for ALTER of constraints in SQLite dialect` (تا `e2f3a4b5c6d7` بالا رفته بود) |
| ۸ | شمارش routeها با import واقعی `app.main` (اسکریپت inventory خارج از مخزن) | ۲۰۶ عملیات / ۶۵ ادمین / ۰ بدون guard |
| ۹ | `git status --short --branch` | آرشیو `.git` ندارد؛ زیر مخزن والد `main` @ `ef56c37` به‌صورت untracked |

مشاهدات جانبی اجرا: هنگام pytest دو SAWarning مربوط به pooled connection در `test_phase10_auto_publish` و ... ثبت شد (بدون اثر بر نتیجه)؛ محیط اجرا Python 3.12.16 / Node 24.22.3 است و ممکن است با CI مالک کمی متفاوت باشد.

## ۵. تست‌های اجرا‌نشده و دلیل دقیق

| تست/بررسی | دلیل عدم اجرا |
|---|---|
| `test_phase4_postgres_smoke.py` (۱ skip) | نیاز به `PHASE4_PG_URL` روی PostgreSQL واقعی دارد و در teardown جدول‌ها را drop می‌کند؛ PostgreSQL در این سندباکس موجود نیست و وصل‌شدن به DB واقعی/توسعه ممنوع است. **هیچ‌گاه به DB قابل‌نگهداری اشاره نشود** |
| `alembic upgrade head/check` روی PostgreSQL از `d4e5f6a7b8c9` به بعد | بدون PostgreSQL؛ در سندباکس فقط SQLite در دسترس بود (که خودش به یافتهٔ شکست انجامید) |
| تست‌های کیفیت مدل واقعی / OCR / transcription واقعی | خروج از محدودهٔ فاز؛ مستندات خودشان می‌گویند ارزیابی مدل جداگانه لازم است |
| Redis واقعی (rate limiter) | سرویس اجرا نشد؛ مسیر fallback درون‌پردازه‌ای با تست پوشش داده شده است |
| QA مرورگری RTL/KaTeX/Mermaid/پرینت/موبایل | بدون مرورگر در سندباکس؛ در `UI_POLISH_REPORT` هم open ثبت است |

## ۶. ریسک‌های باقیمانده، تصمیم‌های نیازمند مالک، rollback

**ریسک‌ها:**

1. **دروازهٔ lint قرمز است** (۱۲ خطا) و با ادعای «0 errors» سند HOTFIX ناسازگار است — build و تست‌ها سبزند ولی gate lint فعلاً قابل‌اعتماد نیست.
2. **`backend/app/api/admin.py` (۳٬۵۹۶ ل) و `frontend/app/admin/page.tsx` (۳٬۵۲۳ ل)** در مرز نگه‌داری هستند؛ هر فاز UI/ادمین جدید خطر تضاد ادغام دارد.
3. **زنجیرهٔ migration روی SQLite تازه از `f3a4b5c6d7e8` به بعد نمی‌گذرد**؛ و وضعیت revisionهای `d1e2f3a4b5c6`…`d0e1f2a3b4c5` روی PostgreSQL در این محیط اثبات نشده است.
4. **README:7 ادعای امنیتی غلط دارد** («APIهای ادمین احراز هویت ندارند») — گمراه‌کننده برای کاربر جدید.
5. auth legacy ادمین با رمز مشترک (`admin`/`123` پیش‌فرض) حفظ شده — ریسک مستند HOTFIX §11؛ فقط در production guard بسته می‌شود.
6. آرشیو بدون `.git` است؛ اجرای فازهای بعدی باید در checkout واقعی مالک انجام شود تا ارجاع commit معتبر بماند.

**تصمیم‌های نیازمند مالک (blocker ابهام پیش از فاز ۱):**

1. سیاست lint: اصلاح ۷ فایل (`set-state-in-effect`) یا تنظیم قانون/نسخهٔ eslint — قبل از هر فاز UI.
2. نیازمندی پشتیبانی Alembic روی SQLite غیر-demo یا پذیرش «PostgreSQL-only» به‌صورت رسمی در runbook.
3. اصلاح README:7 و مهر تاریخی سندهای PHASE0/RELEASE_READINESS/HOTFIX/UI_POLISH (پیشنهاد در فاز مستندات).
4. تکلیف `/study/[bookId]`: افزودن لینک مستقیم در سایدبار دانش‌آموز یا پذیرش مسیر فعلی (فقط از `/mastery`).
5. زمان‌بندی اجرای `alembic upgrade head + check` روی PostgreSQL اختصاصی خالی، قبل از نخستین فاز دارای migration.

**دستور rollback (ساده — فقط سند):**

```bash
# حذف دقیق سه سند فاز ۰۰ (تنها تغییرات این فاز):
rm docs/REDESIGN_EXECUTION_BASELINE.md docs/REDESIGN_STATUS_MATRIX.md docs/REDESIGN_PHASE_00_REPORT.md
# و برای محیط اجرا (اختیاری): rm -rf backend/.venv frontend/node_modules frontend/.next
```

## ۷. چک‌لیست تست دستی فارسی و مسیرهای UI/API

برای بازبینی مالک پس از اجرای `./scripts/run-live-demo.sh` (demo، SQLite، بدون مدل واقعی):

| # | سناریو | مسیر UI | مسیر API |
|---|---|---|---|
| ۱ | ثبت‌نام موبایل → OTP نمایشی → رمز → ورود بدون reload | `/` → «ورود / ثبت‌نام» → «ثبت‌نام با موبایل» | `POST /api/v1/auth/register/{request-otp,verify-otp,complete}` |
| ۲ | ورود با رمز و خروج (با dialog تأیید) | همان مودال | `POST /auth/login` · `POST /auth/logout` |
| ۳ | بازیابی رمز و ابطال نشست‌های دیگر | «رمز عبورم را فراموش کرده‌ام» | `POST /auth/password/recover/*` |
| ۴ | ورود ادمین (demo: `admin`/`123`) و دیدن ۵ دستهٔ ناوبری + drawer موبایل | `/admin` | `POST /api/v1/admin/auth/login` |
| ۵ | ارائه‌دهنده‌ها: افزودن کلید، تست اتصال، ماسک کلید | `/admin/providers` | `POST /admin/providers` · `POST /admin/providers/{id}/test` |
| ۶ | مرکز شفافیت: فیلتر لاگ audit و drawer پاسخ | `/admin/observability` | `GET /admin/audit-logs` |
| ۷ | نقش‌ها/سهمیه: ویرایش سیاست و override per-feature | `/admin/roles` | `GET/PUT /admin/quotas` |
| ۸ | کاربران: جست‌وجو/فیلتر (ماندگاری در URL بعد از refresh)، تغییر نقش با reauth، ابطال نشست | `/admin` تب «کاربران» · `/admin/users/[id]` | `GET /admin/users` · `PUT /admin/users/{id}/role` |
| ۹ | فلش‌کارت: تولید از کتاب، مرور با ۴ دکمهٔ SM-2، export Anki | `/flashcards` | `POST /flashcards/generate` · `POST /flashcards/{id}/review` · `GET .../export/anki` |
| ۱۰ | پادکست: تولید اپیزود نمایشی، دیدن وضعیت، پخش | `/podcast` | `POST /api/v1/podcasts` · `GET /api/v1/podcasts/{id}` |
| ۱۱ | خوانندهٔ عمیق از مسیر Mastery و لایت‌باکس شکل‌ها | `/mastery` → «مطالعهٔ کتاب» → `/study/[bookId]` | `GET /api/v1/immersive/books/{id}/pages/{n}`(+image) |
| ۱۲ | حل عمیق: پیشروی Hint1 → Hint2 → Step → Full | `/deep-solve` | `POST /deep-solve/sessions/{id}/actions` |
| ۱۳ | بانک اشتباه: ثبت خودکار از آزمونِ ناموفق، تمرین مجدد، ارسال به فلش‌کارت | آزمون در `/` سپس `/mistakes` | `GET /mistakes` · `POST /mistakes/{id}/answer` |
| ۱۴ | مسیر تسلط: تایم‌لاین فصل‌ها و قفل مراحل | `/mastery` | `GET /mastery/books/{id}` |
| ۱۵ | نوت‌بوک: بلوک + پیشنهاد inline و پذیرش/رد + export | `/notebook` | `POST /notebooks/{id}/blocks/{bid}/inline/propose|accept` |
| ۱۶ | کتاب زندهٔ فصل + TTS دکمهٔ صدا | `/living-book` | `GET /living-book/{book}/chapters/{n}` |
| ۱۷ | چت: streaming، توقف/بازیابی، سبد بازیافت | `/` (بخش گفت‌وگو) | `POST /tutor/stream` · `sessions/trash/restore` |
| ۱۸ | ۴۰۳ دانش‌آموز روی مسیر ادمین و ۴۰۱ ناشناس | کنسول مرورگر/شبکه | `GET /admin/providers` با توکن دانش‌آموز → 403 |

## ۸. نتیجهٔ صریح

**PASS** — معیارهای همین فاز اثبات شده‌اند:

- ✅ هیچ فایل اجرایی/migration/کد تغییر نکرده است (فقط ۳ سند جدید در `docs/`).
- ✅ وضعیت auth، workerها، مسیرهای ادمین، auto-publish و RAG از کد و تست استخراج شد، نه از حدس (ماتریس ضمیمه با ارجاع file:line).
- ✅ همهٔ تست‌های اجراشده status واقعی دارند: backend **۴۶۸ passed / ۱ skipped / 0 failed**، frontend **۳۹ passed / 0 failed**، lint **۱۲ خطا / ۲ هشدار (exit 1)**، build **موفق (۲۳ مسیر)** — هیچ شکست، رد نشده یا پنهان نشده است.
- ✅ همهٔ ابهام‌های blocker پیش از فاز ۱ در بندهای ۶ و ۹ سند baseline فهرست شدند (lint policy، Alembic/SQLite و PG، README:7، دسترس‌پذیری `/study`، نبود `.git`، نیاز به سرویس واقعی).

**وارد فاز بعد نمی‌شویم.** طبق قواعد، هیچ commit/push/merge انجام نشده؛ شاخهٔ پیشنهادی برای این تغییرات مستنداتی: `docs/redesign-phase-00-baseline` (تک‌commit شامل سه فایل `docs/REDESIGN_*.md`).
