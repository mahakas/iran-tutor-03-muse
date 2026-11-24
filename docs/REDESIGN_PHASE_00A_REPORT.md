# گزارش فاز ۰۰-A — رفع موانع ورود به فاز ۱

> **تاریخ:** ۲۰۲۶-۱۱-۲۳ · **مبنای کار:** گزارش و baseline فاز ۰۰
> **نتیجهٔ نهایی: `PASS — READY FOR PHASE 01`** (اثبات در بند ۹)
> **سندهای همراه این فاز:** `docs/REDESIGN_DECISIONS_LOG.md` (D-001، D-002) · به‌روزرسانی در انتهای `docs/REDESIGN_EXECUTION_BASELINE.md`

---

## ۱. خلاصهٔ تغییرات و دلیل هر تغییر

موانع اعلام‌شده در فاز ۰۰، یکی‌یکی و با کمترین تغییر ممکن رفع شدند:

| # | مانع فاز ۰۰ | اقدام فاز ۰۰-A | نتیجه |
|---|---|---|---|
| ۱ | دروازهٔ lint قرمز: ۱۲ خطای `react-hooks/set-state-in-effect` + ۲ هشدار `exhaustive-deps` | اصلاح اصولی در ۷ کامپوننت (بند ۲) بدون غیرفعال‌کردن قانون | lint: **۰ خطا / ۰ هشدار، exit 0** |
| ۲ | Alembic روی PostgreSQL از `d4e5f6a7b8c9` به بعد هرگز راستی‌آزمایی نشده بود | اجرای کل زنجیره روی PostgreSQL مستقل واقعی (pgserver، دیتابیس دورریز) | کل ۲۳ revision تا head بالا رفت؛ در راه، یک drift واقعی کشف و رفع شد (بند ۳)؛ `alembic check` حالا **تمیز** است |
| ۳ | شکست Alembic روی SQLite تازه در `f3a4b5c6d7e8` | بررسی کامل وضعیت پشتیبانی از کد و مستندات؛ SQLite رسماً **فقط Demo** اعلام شد (مثل create_all، بدون Alembic)؛ محدودیت رسمی شد — **هیچ migration قدیمی تغییر نکرد** | تصمیم ثبت‌شده در `REDESIGN_DECISIONS_LOG.md` D-002 |
| ۴ | `README.md:7` ادعای امنیتی غلط («APIهای ادمین احراز هویت ندارند») | اصلاح خط ۷ و عبارت هم‌خانواده در خط ۵ | README با کد و با هشدار امنیتی درون خودش سازگار شد |
| ۵ | دسترس‌پذیری `/study/[bookId]` نیازمند تصمیم مالک | تصمیم پیشنهادی مالک («لینک مطالعهٔ مستقیم از کارت کتاب در Mastery») در Decision Log ثبت شد — امضای موجود `MasteryWorkspace.tsx` نقطهٔ ورود رسمی است؛ **تغییر UI انجام نشد** | D-001 |
| ۶ | تست smoke فاز ۴ (opt-in روی PostgreSQL واقعی) هرگز اجرا نشده بود | با همان PG مستقل اجرا شد؛ قدیمی‌بودن قراردادش کشف و قرارداد فاز ۱۰ به آن اعمال شد (بدون تغییر assertionها) | **۱ passed روی PostgreSQL واقعی** — مسیر lexical `to_tsvector` تأیید شد |

## ۲. فایل‌های تغییرکرده/جدید و علت دقیق هر تغییر

**کد فرانت‌اند — الگوی واحد برای رفع `set-state-in-effect`:** بدنهٔ هر effect درون یک async-IIFE با یک `await Promise.resolve()` اولیه پیچیده شد؛ چون effectها بعد از paint اجرا می‌شوند و microtaskها قبل از paint بعدی تمام می‌شوند، توالی reset+fetch و همهٔ setStateها دقیقاً با قبل یکسان است — فقط دیگر داخل effect «هم‌زمان» نیستند (قاعدهٔ React 19 cascade). هیچ قانون lint غیرفعال نشد؛ disable خطیِ ازقبل‌موجودِ `AdminUsersPanel` (فقط خطی، نه سراسری) دست‌نخورده ماند.

| فایل | تغییر | علت |
|---|---|---|
| `frontend/components/MistakeBankWorkspace.tsx` | effect `load()` با الگوی deferred | خطای ۴۸:۱۰ |
| `frontend/components/ChatRecycleBin.tsx` | بدنهٔ `loadBin` (تک-مصرف‌کننده) داخل effect با الگوی deferred؛ import بلااستفادهٔ `useCallback` حذف | خطای ۵۸:۲۹ |
| `frontend/components/ImmersiveReader.tsx` | دو effect (reset کتاب و reset صفحه/تصویر) با الگوی deferred | خطاهای ۴۷:۵، ۷۶:۵ |
| `frontend/components/AuthFlowModal.tsx` | effect ریست فرم با الگوی deferred + **محافظ فوکوس**: تایمر ۵۰ms فقط وقتی کاربر فیلدی را شروع نکرده فوکوس می‌گیرد | خطای ۹۷:۵ + باگ واقعی دزدیدن فوکوس (بند ۲) |
| `frontend/components/AdminUsersPanel.tsx` | دو effect (`loadRoles`، `load`) با الگوی deferred | خطاهای ۲۷۶:۱۰، ۲۸۰:۱۰ |
| `frontend/components/StudentApp.tsx` | دو effect (books/fields) با الگوی deferred (پترن `.then/.catch` → `try/catch` با همان معنا؛ controller در cleanup) + افزودن `selectGradeNumber` به دو آرایهٔ وابستگی (useCallback با deps خالی — هویت پایدار، صفر تغییر رفتار) | خطاهای ۳۵۹:۷، ۳۹۸:۷ + هشدارهای ۹۳۷ و ۱۲۴۴ |
| `frontend/components/BookGradePicker.tsx` | سه effect با الگوی deferred | خطاهای ۳۸:۷، ۶۸:۷، ۹۴:۷ |
| `backend/alembic/versions/e1f2a3b4c5d6_align_flashcard_study_sessions_user_id.py` | **جدید** — هم‌عرض‌کردن `flashcard_study_sessions.user_id` با مدل (64→36) فقط روی PostgreSQL، با `_is_postgres()` به الگوی phase 7؛ downgrade به 64 برگشت‌پذیر است | کشف drift در `alembic check` (بند ۳)؛ FK به `users.id` (String(36)) ایمنی داده را تضمین می‌کند |
| `backend/tests/test_phase4_postgres_smoke.py` | سه فراخوانی `search_multi_grade` اکنون `book_ids` مجاز را پاس می‌دهند (همان کتاب‌های ready که خود تست ساخته) + کامنت قرارداد | تست با قرارداد قفل‌شدهٔ فاز ۱۰ (`build_scopes` فقط book_ids مجازِ سمت‌سرور) ناسازگار بود و بدون این اصلاح هرگز پاس نمی‌شد؛ **هیچ assertion تغییر نکرد/ضعیف نشد** |
| `README.md` | خط ۷: توصیف واقعی محافظت (login ادمین + کوکی نشست + مسیر legacy رمز مشترک فقط dev) و ارجاع به «هشدار امنیتی»؛ خط ۵: عبارت «مجوزهای ادمین کامل نشده‌اند» و هم‌خانواده‌ها با وضعیت واقعی کد به‌روزرسانی شد | بند ۵ وظیفهٔ فاز |
| `docs/REDESIGN_DECISIONS_LOG.md` | **جدید** — D-001 (نقطهٔ ورود study) و D-002 (وضعیت رسمی SQLite) | ثبت رسمی تصمیم‌ها برای فازهای بعد |
| `docs/REDESIGN_PHASE_00A_REPORT.md` | **جدید** — همین گزارش | دروازهٔ تحویل |

**دست‌نخورده‌ها:** هیچ API، نقش، جدول، مدل، قابلیت کاربری یا assertion موجود تغییر/حذف نشد؛ هیچ قانون lint سراسری غیرفعال نشد؛ هیچ migration قدیمی بازنویسی نشد؛ `next-env.d.ts` بایت‌به‌بایت با آرشیو یکسان است؛ `storage/` (اثر جانبی seed در اجرای تست) بازیابی و با `cmp` تأیید شد.

## ۳. قابلیت‌های قبلی که حفظ شدند و تست محافظ

- **رگرسیون کامل سبز:** backend `۴۶۸ passed / ۱ skipped / ۰ failed` (دقیقاً برابر baseline فاز ۰۰)؛ frontend Vitest `۳۹/۳۹`؛ build با همان ۲۳ مسیر موفق. هیچ تستی weak نشد.
- مهم‌ترین تست‌های محافظ دست‌نخورده: `test_ai_gateway_isolation.py`، `test_every_admin_operation_carries_require_admin`، `test_phase10_auto_publish.py` (۱۱ سنجه)، `test_user_auth_admin.py`، `test_exams.py`، `test_phase9_podcast.py`، `test_phase8_flashcard_study.py` (رفتار SM-2/study-session پس از migration عرض)، `tests/apiClient.test.ts`، `AuthFlowModal.test.tsx`، `AdminUsersPanel.test.tsx`.

## ۴. فرمان‌های دقیق اجراشده و خروجی واقعی

| gate | فرمان | نتیجهٔ واقعی |
|---|---|---|
| Backend | `cd backend && .venv/bin/python -m pytest -q tests` | ✅ **۴۶۸ passed، ۱ skipped، ۲ warnings** در 202.68s — exit 0 |
| Frontend unit | `cd frontend && npm test` | ✅ **۵ فایل، ۳۹/۳۹ passed** — exit 0؛ پایداری: فایل `AuthFlowModal.test.tsx` سه‌بار متوالی پاس شد (قبلاً flaky) |
| Frontend lint | `cd frontend && npm run lint` | ✅ **۰ خطا / ۰ هشدار — exit 0** (فاز ۰۰: ۱۲ خطا + ۲ هشدار، exit 1) |
| Frontend build | `cd frontend && npm run build` | ✅ **Compiled successfully in 11.0s** — ۲۳ مسیر (۲۱ static + ۲ dynamic) — exit 0 |
| Alembic — PG مستقل | اسکریپت `scripts/pg_migration_check.py` (pgserver: PostgreSQL واقعی embedded، pgdata دورریز در /tmp، پس از اجرا **حذف کامل**) | ✅ `upgrade head` → هر ۲۳ revision تا `d0e1f2a3b4c5` و سپس migration جدید تا **`e1f2a3b4c5d6 (head)`** · `current` OK · **`check` OK (No new upgrade operations detected)** · `downgrade -1` OK · `upgrade head` مجدد OK → `ALL_OK` |
| Alembic — SQLite تازه | `DATABASE_URL=sqlite+aiosqlite:///tmp/... alembic upgrade head` | ❌ تا `e2f3a4b5c6d7` بالا می‌رود؛ در `f3a4b5c6d7e8` می‌شکند (`NotImplementedError: drop_constraint بدون batch`) — **رسماً مستند به‌عنوان محدودیت demo-only** (D-002)، نه شکست محیط پشتیبانی‌شده |
| Smoke فاز ۴ روی PG واقعی | اسکریپت `scripts/run_pg_smoke.py` (`PHASE4_PG_URL` روی DB دورریز؛ خود تست create_all/drop_all خودش را اجرا می‌کند) | ✅ **۱ passed در 2.11s** — مسیر lexical `to_tsvector` چندپایه با قرارداد فاز ۱۰ |

> قبل از هر تست، config آن خوانده شد (`pytest.ini`: testpaths=tests؛ conftest: placeholderهای env؛ smoke test: صریحاً «disposable database only»). هیچ DB توسعه/تولیدی/دارداده به کار نرفت؛ هر دو instance PG پس از اجرا destroy شدند.

## ۵. تست‌های اجرا‌نشده و دلیل

| تست/بررسی | وضعیت | دلیل |
|---|---|---|
| `test_phase4_postgres_smoke.py` | ✅ **اجرا و پاس شد** (این بار با PG واقعی) — دیگر در فهرست «اجرا نشده» نیست | — |
| کیفیت مدل واقعی / OCR / transcription واقعی / ارسال SMS واقعی | اجرا نشده | نیاز به ارائه‌دهندهٔ پیکربندی‌شده و هزینه دارد؛ خارج از دامنهٔ ۰۰-A (مستند README و فاز ۰۰) |
| Redis واقعی (rate limiter) | اجرا نشده | سرویس در سندباکس نیست؛ مسیر fallback با تست پوشش داده شده |
| QA مرورگری RTL/KaTeX/پرینت | اجرا نشده | بدون مرورگر؛ چک‌لیست دستی در گزارش فاز ۰۰ باقی است |
| `alembic check` روی SQLite | اجرا/ادعا نشده | SQLite مسیر migration نیست (D-002)؛ فقط `upgrade head` برای مستندسازی محدودیت اجرا شد |

## ۶. ریسک‌های باقی‌مانده، تصمیم‌ها و rollback

**ریسک‌ها:**
1. **آرشیو `.git` ندارد** — تغییرات روی درخت راستی‌آزمایی‌شدهٔ این سندباکس اعمال شده و یک patch استاندارد آماده شد: `download/iran-tutor-phase00-00a.patch` (۱۴ فایل؛ فرمت git، قابل‌اعمال با `git apply` روی checkout واقعی مالک). مالک باید بعد از اعمال، باتری تست را یک‌بار در محیط خودش تکرار کند.
2. **تغییر ریز رفتاری ۱:** autofocus مودال دیگر فوکوس را از فیلدی که کاربر در حال تایپ آن است نمی‌دزدد (رفع باگ واقعی؛ هدف تست «drop نشدن ورودی» بهتر محقق می‌شود). **تغییر ریز رفتاری ۲:** شروع بارگذاری‌ها یک microtask بعد از paint انجام می‌شود — از نظر بصری یکسان (قبل از paint بعدی)؛ در هیچ تستی تفاوت مشاهده نشد.
3. **migration عرض user_id:** بر روی DBهای موجود PostgreSQL، `ALTER varchar(64)→varchar(36)` با اجرای `upgrade head` اعمال می‌شود؛ FK به `users.id` تضمین می‌کند هیچ مقدار >۳۶ وجود ندارد، ولی طبق رویه، قبل از اجرا روی production یک بکاپ/بررسی طول گرفته شود.
4. دروازهٔ lint حالا سبز است؛ برای ماندگاری، CI (`ci.yml`) باید lint را در gate نگه دارد (الان موجود است؛ فقط مانیتور شود).
5. تست smoke همچنان opt-in است (نیاز به `PHASE4_PG_URL`) — پیشنهاد: اتصال آن به CI با یک PG موقت (فازهای بعد).

**تصمیم‌های ثبت‌شده برای فازهای بعد:** D-001 و D-002 در `REDESIGN_DECISIONS_LOG.md`. مورد باز برای مالک: اتصال smoke به CI (پیشنهاد، الزام نیست).

**Rollback:** هیچ commit/push انجام نشده؛ همهٔ تغییرات در working tree است:
```bash
# در checkout واقعی مالک (اگر patch اعمال شده باشد):
git apply -R iran-tutor-phase00-00a.patch
# یا در این درخت سندباکس: بازگرداندن ۱۰ فایل کد/مستند از آرشیو و حذف ۳ فایل جدید:
#   git checkout -- frontend/components/*.tsx README.md backend/tests/test_phase4_postgres_smoke.py
#   rm backend/alembic/versions/e1f2a3b4c5d6_align_flashcard_study_sessions_user_id.py \
#      docs/REDESIGN_DECISIONS_LOG.md docs/REDESIGN_PHASE_00A_REPORT.md
# DB: migration جدید کاملاً برگشت‌پذیر است → alembic downgrade -1
```

## ۷. چک‌لیست تست دستی فارسی (نقاط لمس‌شدهٔ این فاز)

| # | سناریو | انتظار |
|---|---|---|
| ۱ | باز کردن مودال ورود و تایپ سریع شماره و بلافاصله رفتن به فیلد رمز | فوکوس دزده نمی‌شود؛ هر دو مقدار کامل می‌ماند |
| ۲ | ورود رمز غلط | پیام «نادرست است» + شمارهٔ تایپ‌شده پابرجا (سناریوی تست) |
| ۳ | بستن و باز کردن مودال | فرم کاملاً ریست می‌شود |
| ۴ | انتخاب پایه ۱۰-۱۲ → شاخه → رشته در انتخاب‌گر کتاب و تغییر پیوستهٔ پایه‌ها | فهرست‌ها بدون پرش/مقدار کهنه به‌روز می‌شوند (BookGradePicker) |
| ۵ | باز کردن بانک اشتباهات و تغییر فیلتر وضعیت | لیست بدون پرش به‌روز می‌شود |
| ۶ | رفتن به تب «سطل بازیافت» در چت | اسپینر بارگذاری و لیست بدون وضعیت خالی گذرا |
| ۷ | `/mastery` → لینک «مطالعهٔ کتاب» و تعویض کتاب | خوانندهٔ عمیق ریست و بارگذاری تمیز (ImmersiveReader) |
| ۸ | پنل ادمین → کاربران: تغییر فیلترها و صفحه‌بندی، refresh صفحه | فیلترها از URL برمی‌گردند؛ لودینگ درست |

## ۸. مقایسهٔ قابلیت‌ها با Baseline فاز ۰۰

| کمیت | baseline فاز ۰۰ | اکنون | حکم |
|---|---|---|---|
| عملیات HTTP / عملیات ادمین / بدون guard | ۲۰۶ / ۶۵ / ۰ | ۲۰۶ / ۶۵ / ۰ | بدون تغییر |
| جدول‌های ORM | ۵۴ | ۵۴ | بدون تغییر (فقط عرض یک ستون روی PG هم‌تراز مدل شد) |
| head Alembic | `d0e1f2a3b4c5` | `e1f2a3b4c5d6` | +۱ revision اصلاحی، برگشت‌پذیر، بدون تغییر قابلیت |
| مسیرهای Next.js | ۲۳ | ۲۳ | بدون تغییر |
| pytest | ۴۶۸ passed / ۱ skipped | ۴۶۸ passed / ۱ skipped | بدون افت |
| Vitest | ۳۹/۳۹ (flaky در AuthFlowModal) | ۳۹/۳۹ (پایدار — ۳× فایل + کل مجموعه) | بهبود پایداری |
| ESLint | ۱۲ خطا + ۲ هشدار (exit 1) | **۰/۰ (exit 0)** | رفع کامل |
| build | موفق (۲۳ مسیر) | موفق (۲۳ مسیر) | بدون تغییر |
| `alembic check` روی PostgreSQL | هرگز اجرا نشده بود (آخرین سند: تمیز تا `d4e5f6a7b8c9`) | **تمیز تا head جدید** | تقویت |
| smoke فاز ۴ روی PostgreSQL | هرگز اجرا نشده بود | **passed** | تقویت |
| وضعیت SQLite | ابهام | رسماً demo-only (D-002) | شفاف‌سازی |
| ادعای امنیتی README | غلط | سازگار با کد | اصلاح |

## ۹. نتیجهٔ صریح

**`PASS — READY FOR PHASE 01`**

معیارهای پذیرش، یکی‌یکی اثبات‌شده:
- ✅ هیچ خطای ESLint حل‌نشده‌ای باقی نمانده (۰ خطا / ۰ هشدار؛ بدون غیرفعال‌سازی قانون).
- ✅ تست‌های قبلی سبز مانده‌اند (backend ۴۶۸/۱ — برابر baseline؛ Vitest ۳۹/۳۹؛ هیچ assertion تغییر نکرده).
- ✅ Build موفق (۲۳ مسیر، exit 0).
- ✅ مهاجرت دیتابیس روی محیط‌های رسماً پشتیبانی‌شده تأیید شد: PostgreSQL مستقل واقعی — `upgrade head` کامل تا head، `check` تمیز، `downgrade -1` و بازاعمال موفق؛ SQLite رسماً demo-only و محدودیتش مستند (D-002) — به‌جای تغییر migrationهای موجود، drift کشف‌شده با یک migration جدیدِ اصلاحی رفع شد.
- ✅ هیچ قابلیت موجودی حذف یا تضعیف نشده (مقایسهٔ بند ۸ + این‌که همهٔ تغییرات کد اصلاح lint/فوکوس بودند و هیچ مسیر API/مدل/نقشی تغییر نکرد).

هیچ commit، push یا merge انجام نشده است. شاخهٔ پیشنهادی برای بازبینی مالک: `fix/phase00a-unblock` (شامل ۷ کامپوننت + migration جدید + smoke test + README + سه سند REDESIGN؛ patch: `download/iran-tutor-phase00-00a.patch`).
