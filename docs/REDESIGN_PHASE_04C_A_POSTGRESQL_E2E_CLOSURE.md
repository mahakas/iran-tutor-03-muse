# Darsyar — Phase 04C-A: PostgreSQL E2E Closure, Regression Fixes & Phase 05 Handover

تاریخ: 2026-11-24 · شاخه: `main` · Commit پایه: `7db4f35` · وضعیت نهایی: **PASS — PHASE 04C-A CLOSED — READY FOR PHASE 05**

---

## ۱. Git Audit و فایل‌های تغییرکرده

حادثهٔ محیطی مهم: در ابتدای این نشست، دایرکتوری `iran-tutor-main/` (شامل `.git` با commit پایهٔ `7db4f35`) در بازیافت sandbox از بین رفته بود. کل پروژه با تمام تغییرات Phase 04B و 04C از آرشیو `iran-tutor-phase04C-complete.zip` (تهیه‌شده در پایان نشست قبل) بازسازی و با `git log` / `grep` راستی‌آزمایی شد: commit پایهٔ `7db4f35` و هر ۱۲ فایل تغییرکردهٔ قبلی عیناً بازگشتند. برای حافظت از working tree یک patch پشتیبان نیز خارج از repo ذخیره شد:

- `download/phase04c_a/backup/phase04B_04C_tracked_changes.patch` (۸۸۸ خط، diff کل تغییرات tracked در ابتدای نشست)
- کپی فایل‌های untracked قبلی (`b5c6d7e8f9a0…py`، گزارش 04C) در همان پوشه

**فایل‌های متعلق به Phase 04B/04C (پیش از این نشست — دست‌نخورده ماندند):** `backend/app/models/governance.py`، `backend/app/services/ai_gateway.py`، `backend/app/services/capability_runtime.py`، `backend/app/services/podcast_service.py`، `backend/app/services/quota_service.py*`، `docs/REDESIGN_PHASE_04B_…md`، `frontend/components/PodcastPlayerProvider.tsx`، `frontend/components/PodcastWorkspace.tsx`، `frontend/tests/PodcastPlayerPersistence.test.tsx`، `frontend/tests/PodcastWorkspace.test.tsx`، `backend/alembic/versions/b5c6d7e8f9a0_…py` (untracked)، `docs/REDESIGN_PHASE_04C_…md` (untracked).

**فایل‌های ایجاد/تغییر‌یافته در همین نشست (04C-A):**

| فایل | نوع | خلاصهٔ تغییر |
|---|---|---|
| `backend/app/services/quota_service.py` | ویرایش | افزودن `peek_quota_counters` (گیتِ فقط-خواندنی) و اتصال `enforce_ai_quota` به آن؛ حذف INSERT ناتمام از مسیر گیت |
| `backend/tests/test_podcast_quota_gate.py` | جدید | ۲ تست regression بن‌بست (SQLite + PostgreSQL opt-in با `PODCAST_PG_URL`) |
| `backend/tests/test_phase7_followup.py` | ویرایش (+۶ خط) | hermetic کردن تست alias تنظیمات (عایق از فایل `.env` محیط QA) |
| `docs/REDESIGN_PHASE_04C_A_POSTGRESQL_E2E_CLOSURE.md` | جدید | همین گزارش |

سایر تغییرات working tree (مثل `podcast_service.py`، `PodcastWorkspace.tsx`) متعلق به فازهای قبل است و توسط این نشست تغییر نکرده است (مطابقت byte-level با محتوای استخراج‌شده از ZIP نگه داشته شد). هیچ commit و push انجام نشده است؛ `git diff --cached` خالی است.

## ۲. علت ریشه‌ای توقف UI روی PostgreSQL

مشکل با اجرای واقعی بازتولید شد: ساخت پادکست از UI روی PostgreSQL ایزولهٔ QA اپیزود ۷ را ساخت که دقیقاً روی `progress=15 / stage=تولید متن گفت‌وگو` قفل شد و heartbeat آن ~۱۵ دقیقه ثابت ماند. در همان لحظه از PostgreSQL شواهد زنده گرفته شد:

- `pg_stat_activity`: نشست worker با `state='idle in transaction'` (سن ۱۳۵.۷ ثانیه)، آخرین جمله: `SELECT … feature_model_routes`
- نشست دوم: `INSERT INTO user_quotas …` با `wait_event='Lock/transactionid'` (سن ۱۳۵.۱ ثانیه)
- `pg_blocking_pids`: نشست دوم توسط PID نشست worker مسدود است؛ `pg_locks`: ۱ قفل بی‌اعطا

**زنجیرهٔ بن‌بست (self-deadlock):**

1. تراکنشِ بازِ worker (یک session برای کل طول تولید) در گیتِ پیش از فراخوانی، `enforce_ai_quota` → `get_or_create_quota` را صدا می‌زند؛ برای اولین مصرفِ هر (user, feature) این تابع یک ردیف جدید `user_quotas` را با `session.flush()` **داخل همان تراکنش بلندمدت** INSERT و «ناتمام» نگه می‌دارد (pending unique-index entry روی `ux_user_quotas_user_feature`).
2. worker سپس فراخوانی شبکهٔ Provider (اسکریپت/TTS) را با همان تراکنش باز انجام می‌دهد.
3. حسابداری Phase 04C (`audit_in_own_transaction`) در یک نشستِ کوتاه جداگانه `increment_quota_counters` را اجرا می‌کند — `INSERT … ON CONFLICT DO UPDATE` روی همان (user_id, feature_key) — که طبق رفتار مستند PostgreSQL باید منتظر تعیین تکلیف ردیف ناتمامِ تراکنش worker بماند.
4. worker هم منتظر همان نشست حسابداری است (gateway قبل از ادامه، `_write_audit` را await می‌کند) → **دور انتظارِ بسته و دائمی**؛ progress هرگز از ۱۵٪ عبور نمی‌کند.

شواهد نهایی پس از مرگ worker (اپیزود ۷): ردیف audit اسکریپت `audio_podcast_script|success` ثبت شده بود (نشست جدا حسابداری audit آزاد بود)، اما جدول `user_quotas` **کاملاً خالی**، `podcast_segments` = ۰ و `script_json`/progress بعدی هرگز commit نشدند. اجرای مستقل worker در نشست قبل فقط به این دلیل موفق بود که ردیف quota مربوطه از قبل وجود داشت (اولین مصرف نبود) — بن‌بست تنها در اولین مصرفِ هر feature رخ می‌دهد؛ به همین دلیل در تست‌های SQLite هم دیده نمی‌شد (single-writer).

رفع مشکل صرفاً با افزایش timeout نبود و هیچ خطایی هم پنهان نشد؛ علت از روی قفل‌های زندهٔ PostgreSQL اثبات شد.

## ۳. اصلاح انجام‌شده

اصلاح حداقلی در `backend/app/services/quota_service.py`:

- تابع جدید `peek_quota_counters(session, user_id, feature_key, now)` — خوانش **فقط-خواندنی** شمارنده‌ها با اعمال rollover روز/ماه در حافظه (بدون هیچ نوشتن). ردیفِ غایب = صفرِ مصرف.
- `enforce_ai_quota` دیگر `get_or_create_quota` را صدا نمی‌زند و به `peek_quota_counters` متصل شد؛ سه شرط سقف (۴۰۲/۴۰۲/۴۲۹) و `QuotaDecision` با همان معناشناسی قبلی کار می‌کنند.
- نتیجه: هیچ تراکنشی دیگر ردیف `user_quotas` را ناتمام نگه نمی‌دارد؛ ردیف فقط پس از مصرف، توسط upsert اتمیکِ نشستِ کوتاه حسابداری ساخته/به‌روز می‌شود. ترتیب قفل‌ها بین Gateway و Worker دیگر متضاد نیست؛ Idempotency و حسابداری اعتبار دست‌نخورده ماندند (upsert اتمیک `x = x + n` همان نسخهٔ 04C است).
- طراحی commit مرحله‌ایِ worker (`_touch` با flush+commit پس از هر مرحله) که در 04C موجود بود حفظ شد؛ پس از اصلاح، در حین انتظار برای شبکه/TTS فقط خوانش‌های بدون قفل‌نویسی باز است.

## ۴. تست Regression جدید

`backend/tests/test_podcast_quota_gate.py` — هر دو تست با الگوی opt-in پروژه (متغیر محیطی) نوشته شده‌اند:

1. `test_enforce_ai_quota_leaves_no_pending_quota_writes` (هر dialect): پس از گیت، session نباید نوشتن pending داشته باشد.
2. `test_accounting_upsert_not_blocked_by_gate_session` (opt-in PostgreSQL با `PODCAST_PG_URL`، روی دیتابیس آزمایشی اختصاصی `darsyar_qa04c_a`): در حین باز بودن تراکنشِ گیت در session اول، upsert حسابداری از session دوم باید در مهلت ۱۰ ثانیه commit شود.

**اثبات fail-before / pass-after:** پیش از اصلاح، تست ۲ روی PostgreSQL واقعی در ۱۱.۳s شکست خورد (بن‌بست کامل؛ همان رفتار زندهٔ اپیزود ۷). پس از اصلاح، هر دو تست روی PostgreSQL واقعی در ۱.۳s سبز شدند.

## ۵. نتیجهٔ PostgreSQL E2E از UI تا Completed

سه اپیزود کامل از UI واقعی (Playwright → `http://127.0.0.1:3100` → backend واقعی → PostgreSQL ایزولهٔ QA → Provider آزمایشی/QA):

| اپیزود | سناریو | نتیجه | مدت واقعی |
|---|---|---|---|
| ۸ | تولید کامل پس از اصلاح (کش خالی) | `completed` در ~۴s | ۲۰۰.۳۶s |
| ۹ | اجرای مجدد (TTS cache hits) | `completed` — بدون هزینهٔ quota | ۲۰۰.۳۶s |
| ۱۰ | اجرای مانیتورشده با کش پاک‌شده | `completed` — ثبت شواهد کامل | ۲۰۰.۳۶s |

اپیزود ۱۱ نیز توسط QA مرورگر 04B (بند ۶) از UI ساخته و تا `completed` رفت. ده‌گانهٔ پذیرش:

1. درخواست UI موفق — `POST /api/v1/podcasts` → `202` (لاگ HTTP در شواهد) ✓
2. Job ایجاد و claim شد — `started_at` ثبت، status جریان `generating_script → generating_audio → assembling_audio → completed` از DB واقعی ✓
3. Script تولید و ثبت شد — `script_json` present، audit `audio_podcast_script` ✓
4. TTS تمام بخش‌ها — ۱۰ سگمنت `ready`، audit `audio_podcast_tts` × ۱۰ ✓
5. FFmpeg — `storage/podcast_audio/ep-10/episode.mp3` ساخته شد (۲,۴۰۴,۶۶۷ بایت) ✓
6. `completed` — progress=100، stage=«تکمیل» ✓
7. Duration واقعی — ۲۰۰.۳۶s (اندازه‌گیری ffprobe روی خروجی واقعی؛ ۱۰×۲۰s) ✓
8. Quota دقیقاً یک‌بار — پیش از اپیزود ۱۰: `audio_podcast_tts 430/430 tokens, 10 req`؛ پس از آن: `860/860, 20` → دلتا = دقیقاً ۴۳۰ توکن و ۱۰ درخواست برای یک تولید (بدون مصرف تکراری)؛ اپیزود ۹ (cache hit) هیچ دلتایی نداشت ✓
9. بدون Job/Reservation ناسازگار — پس از اجراها: `idle in transaction` = ۰ ✓
10. بدون Deadlock — `pg_blocking_pids` خالی = ۰ در پایان همهٔ اجراها ✓

شواهد ذخیره‌شده: `download/phase04c_a/evidence/` — اسکرین‌شات‌های مراحل (login، فرم، submit، stalled پیش از اصلاح، completed پس از اصلاح)، `repro_evidence.json` (لاگ HTTP، حالت‌های DB ثانیه‌به‌ثانیه، quota قبل/بعد)، لاگ‌های pytest/vitest/tsc/eslint/build، و تصاویر QA مرورگر 04B.

## ۶. وضعیت Job و Worker

- مسیر کامل `PodcastWorkspace → API → Job/Queue → Worker → Script → TTS → FFmpeg → Completed → Quota Settlement` با worker درون-پروسهٔ همان backend (نه فرآیند جدا) و از UI رانده شد — اجرای مستقل worker جایگزین این آزمون نبود.
- Stale recovery رفتار سالم خود را حفظ کرد: اپیزودهای ۶ و ۷ (قربانیان پیش از اصلاح که workerشان با ری‌استارت/اصلاح مرد) توسط مکانیزم موجود به `failed/worker_lost` علامت خوردند؛ هیچ رکورد نیمه‌تمامِ گمراه‌کننده‌ای باقی نماند.
- Cancel/Retry: تست‌های backend مربوطه در سوییت کامل سبز‌اند (بند ۹)؛ مکانیزم claim و قفل تکراری-claim دست‌نخورده است.

## ۷. شواهد Quota و Accounting

- `increment_quota_counters` (upsert اتمیک 04C) دست‌نخورده و سالم: تست‌های `record_ai_usage`/idempotency/concurrency در سوییت کامل سبز.
- آزمون زندهٔ دلتا (اپیزود ۱۰): +۴۳۰ توکن / +۱۰ درخواست برای دقیقاً یک تولید کامل؛ اجرای cache-hit (اپیزود ۹) صفر دلتا — «cache hits cost nothing» برقرار.
- جدول `user_quotas` در QA: ۲ ردیف = ۲ کلید یکتا (بدون تکرار)؛ unique index فعال (بند ۱۱).
- صفحات `ai_audit_logs`: `audio_podcast_script` (۵ success، ۳ flagged — پرچمِ «rag_miss در حالت textbook_strict» رفتار عمدی گیت است) و `audio_podcast_tts` (۲۰ success) — هیچ ردیف شکسته/تکراری.

## ۸. وضعیت تراکنش‌ها و Deadlock

- پیش از اصلاح (حین توقف): ۱ نشست `idle in transaction`، ۱ نشست مسدود روی `Lock/transactionid`، ۱ قفل بی‌اعطا — زنده ثبت شد.
- پس از اصلاح و سه اجرای کامل + QA مرورگر: `idle in transaction` = ۰، نشست مسدود = ۰، قفل بی‌اعطا = ۰.
- ترتیب قفل‌ها اکنون سازگار است: تنها نویسندهٔ `user_quotas` نشستِ کوتاه حسابداری است؛ worker دیگر نویسندهٔ آن جدول در تراکنش بلند نیست.

## ۹. نتیجهٔ کامل `pytest -q`

`cd backend && pytest -q` — پس از آخرین اصلاح، دو بار اجرا شد (دوم برای تأیید نهایی):

- **کل تست‌ها: 512** → **Passed: 510 · Failed: 0 · Skipped: 2** · مدت: **~236s (0:03:56)**
- خطاها: ندارد. دو Skip هر دو opt-in مشروع هستند (نه حذف برای سبز شدن): `test_phase4_postgres_smoke` و `test_podcast_quota_gate::test_accounting_upsert_…` که هر دو با ست‌کردن متغیر محیطی روی PostgreSQL واقعی اجرا و **سبز** شدند:
  - `PHASE4_PG_URL` + `test_phase4_postgres_smoke.py` و `test_phase4_memory_rag_streaming.py` → **34 passed**
  - `PODCAST_PG_URL` + `test_podcast_quota_gate.py` → **2 passed**؛ `test_postgres_lexical.py` → 3 passed
- پوشش خواسته‌شدهٔ جداگانه — Podcast lifecycle، Quota/Reservation، `record_ai_usage`، Worker/Job claim، Retry/Cancel، Stale recovery، TTS cache، PostgreSQL concurrency، Accounting/Idempotency — همگی در سوییت کامل موجود و پاس.
- یادداشت محیط: اجرای سوییت با `.env` محیط QA انجام شد؛ تنها تداخلش با تست تنظیمات (بند زیر) با hermetic کردن همان تست رفع شد — `.env` تغییر نکرد.

## ۱۰. نتیجهٔ کامل Frontend tests و Build

`cd frontend` — هر چهار دستور با exit code 0:

- `npx vitest run` → **14 فایل / 137 تست، همه passed** (از جمله `PodcastPlayerPersistence.test.tsx` با ۲۷ تست شامل هر دو بستهٔ «persistent playback (Phase 04B)» و «playback state contract (Phase 04C)» و MediaSession؛ و `PodcastWorkspace.test.tsx` با ۹ تست) — فایل حساس 04B/04C به نسخهٔ پایه برگردانده نشد و کامل ماند.
- `npx tsc --noEmit` → بدون خطا
- `npx eslint .` → بدون خطا
- `npm run build` → موفق (خروجی static/dynamic کامل)

## ۱۱. Migration و وضعیت Alembic

`backend/alembic/versions/b5c6d7e8f9a0_quota_accounting_integrity.py` بررسی شد:

- **یک head**: `alembic heads` → فقط `b5c6d7e8f9a0`؛ `alembic current` روی DB QA همین است. گراف با merge point در `d1e2f3a4b5c6` بدون head دوم.
- **سازگاری با مدل**: ایندکس `ux_user_quotas_user_feature(user_id, feature_key, unique)` دقیقاً با تعریف `UserQuota` در `governance.py` منطبق است؛ در DB QA موجود و فعال است (پرس‌وجوی `pg_indexes`).
- **Upsert اتمیک / Lost Update**: مسیر نوشتن، `INSERT … ON CONFLICT DO UPDATE` با `x = x + :n` سمت سرور است؛ تست‌های concurrency پاس‌اند.
- **معنای ستون‌های جمع‌شده**: ادغام تکراری‌ها با SUM روی `daily_tokens_used/monthly_tokens_used/daily_requests_used` انجام می‌شود تا «مصرفِ حساب‌شده ناپدید نشود». نکتهٔ ثبت‌شده: اگر ردیف‌های تکراری به پنجره‌های متفاوت تعلق داشته باشند، جمع در جهت محافظه‌کارانه (بیش‌شماری) است — برای گیتِ سهمیه امن است و در شواهد QA واقعی (دویدگیِ first-touchِ هم‌روز) اتفاق نمی‌افتد. `window_date/window_month` ردیف برندهٔ جدیدتر حفظ می‌شود.
- **Downgrade**: فقط حذف ایندکس است؛ **ادغام ردیف‌ها برگشت‌پذیر کامل نیست** — این موضوع در docstring خود migration صریحاً ثبت شده («merged rows cannot be un-merged») و هیچ rollback تخریبی روی دیتابیس انجام نشد.
- Migration جدیدی لازم نبود (اصلاح در لایهٔ سرویس بود).

## ۱۲. موارد باقی‌ماندهٔ PARTIAL

خارج از محدودهٔ این فاز — همچنان PARTIAL و با PASS اشتباه گرفته نشده‌اند:

1. Provider تجاری واقعی (مثل Z_ai/OpenAI تولیدی): همهٔ اجراها با **Fake/QA Provider** کنترل‌شده (`scripts/qa04b/fake_provider.py` — صراحتاً fake) انجام شد؛ مسیر شبکهٔ واقعی vendor آزموده نشده است.
2. آزمون Android/iOS روی دستگاه فیزیکی (MediaSession واقعی دستگاه).
3. هم‌گام‌سازی پخش بین دستگاه‌ها و بازطراحی Player/Podcast Studio (خارج از محدوده).
4. پرچم‌های `flagged` گیت strict-mode در audit اسکریپت: رفتار عمدی است اما تصمیم محصولی دربارهٔ آن در فاز بعد می‌تواند بررسی شود.

## ۱۳. Rollback دقیق و محدود به تغییرات این نشست

Rollback فقط این سه تغییر 04C-A را برمی‌گرداند و **هیچ تغییر تأییدشدهٔ 04B/04C را حذف نمی‌کند**:

```bash
cd /home/z/my-project/iran-tutor-main
# 1) بازگرداندن گیتِ فقط-خواندنی به نسخهٔ قبل از 04C-A (بدون دست‌زدن به بقیهٔ hunks فایل):
#    تابع peek_quota_counters را حذف و در enforce_ai_quota، بلوک
#    «read-only gate (Phase 04C-A)» را با فراخوانی قبلی get_or_create_quota جابه‌جا کن.
#    (نسخهٔ مرجع در download/phase04c_a/backup/phase04B_04C_tracked_changes.patch)
# 2) حذف فایل تست جدید:
rm backend/tests/test_podcast_quota_gate.py
# 3) حذف بلوک ۶ خطی hermetic در tests/test_phase7_followup.py::test_settings_read_environment_alias
# 4) حذف این گزارش:
rm docs/REDESIGN_PHASE_04C_A_POSTGRESQL_E2E_CLOSURE.md
```

هیچ migration جدیدی اضافه نشده، هیچ داده‌ای در DB تغییر ساختاری نکرده، و هیچ commit/push وجود ندارد که نیاز به بازگردانی داشته باشد.

## ۱۴. حکم نهایی و آمادگی ورود به Phase 05

| معیار | شرط | وضعیت |
|---|---|---|
| PostgreSQL UI E2E | ساخت اپیزود از UI تا Completed | ✅ اپیزودهای ۸، ۹، ۱۰، ۱۱ از UI واقعی تا `completed` |
| Quota | حسابداری دقیق و بدون مصرف تکراری | ✅ دلتای دقیق +۴۳۰/+۱۰ برای یک تولید؛ cache-hit رایگان |
| Database | بدون Deadlock حل‌نشده و تراکنش معطل | ✅ ۰ نشست مسدود / ۰ idle-in-transaction پس از اجراها |
| Backend | اجرای کامل تست‌ها پس از آخرین اصلاح | ✅ 510 passed / 0 failed / 2 opt-in skipped + نسخه‌های PG سبز |
| Frontend | تست، TypeScript، ESLint و Build موفق | ✅ 137 passed، tsc/eslint/build exit 0 |
| Migration | یک Alembic head و Schema سالم | ✅ head یکتا `b5c6d7e8f9a0`، ایندکس یکتا فعال |
| Regression | قابلیت‌های 04B و 04C سالم | ✅ QA مرورگر 04B: 16/16 PASS؛ سوییت‌های واحد سبز |
| Git | همهٔ تغییرات قبلی حفظ‌شده، بدون Commit/Push | ✅ diff پایه با patch پشتیبان منطبق؛ staged=0 |

Provider واقعی و آزمون دستگاه فیزیکی به‌عنوان محدودیت‌های مستقل ثبت شدند و مانع ورود به Phase 05 نیستند (وابستگی مشخصی در محدودهٔ Phase 05 به آن‌ها یافت نشد).

**PASS — PHASE 04C-A CLOSED — READY FOR PHASE 05**
