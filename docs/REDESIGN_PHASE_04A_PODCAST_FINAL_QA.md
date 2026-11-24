# QA نهایی پادکست — Phase 04A

> تاریخ: ۲۰۲۶-۱۱-۲۴ · محیط: staging محلی (:8001 + PostgreSQL 16) و مجموعهٔ کامل تست‌ها
> ## حکم: `PARTIAL — UI VERIFIED, REAL AUDIO PENDING`

---

## ۱) تست تولید واقعی صوت — **انجام‌نشده** (precondition برقرار نیست)

طبق دستور فاز، هرگز PASS فرضی اعلام نشد. شواهد دقیق بررسی:

| بررسی | نتیجه واقعی |
|---|---|
| جدول `ai_providers` در DB staging | **۰ ردیف** — هیچ Provider صوتی (یا هر provider دیگری) ثبت نشده |
| جدول `feature_model_routes` | **۰ ردیف** — روت `audio_podcast_tts` تنظیم نشده |
| قابلیت `audio_podcast` | فعال است، اما `host_a_voice / host_b_voice / narrator_voice` خالی |
| `GET /api/v1/podcasts/config` روی staging | **503** — «صدای پادکست توسط مدیر تنظیم نشده است» (دو بار، صبح و پس از اصلاحات) |
| `demo_mode` | فعال نیست → مسیر demo مجاز نیست |
| ساخت اپیزود روی staging | ممکن نیست؛ `create_episode` پیش از درج ردیف در گیت صدای 503 متوقف می‌شود — بنابراین هیچ اپیزود جعلی ساخته یا PASS فرضی نشد |

**آنچه بدون صوت واقعی اثبات شد (با provider فیک در تست‌های backend):** تولید اسکریپت از منابع، اعتبارسنجی Pydantic + repair، مونتاژ (assemble) با اندازه‌گیری duration واقعی از بایت‌های صوت، timestamps واقعی segment از جمع طول قطعه‌ها (هرگز حدسی)، transcript، دانلود، streaming با Range. این‌ها «UI/سرویس verified» هستند، نه «Real Audio Verified».

**دستورالعمل فعال‌سازی برای مالک (پیش‌شرط تکرار تست):**
1. در پنل ادمین، یک Provider با قابلیت `tts` ثبت شود (کلید واقعی TTS-capable).
2. در `feature_model_routes` روت `audio_podcast_tts` به همان Provider تنظیم شود.
3. در قابلیت `audio_podcast` سه صدا (host_a/host_b/narrator) پر شود.
4. سپس این چک‌لیست اجرا شود: ساخت اپیزود از کتاب ready → تماشای progress واقعی → دانلود فایل نهایی → پخش با پلیر → مقایسهٔ زمان‌های segment با صوت واقعی → sync متن → seek/timeline → لغو میانهٔ تولید → retry.
5. بعد از آن، حکم می‌تواند به `PASS — PODCAST REAL AUDIO VERIFIED` ارتقا یابد.

## ۲) یکپارچگی منابع — **اصلاح شد و اثبات شد**

بررسی `resolve_podcast_sources` یک **ناسازگاری واقعی** پیدا کرد: کد صفحات `needs_review` را هم منبع می‌گرفت در حالی که پیام خطای خودش ادعا می‌کرد «صفحات تأییدنشده استفاده نمی‌شوند». اصلاح انجام شد:

- `podcast_service.py:265-270` — فیلتر منبع فقط `PageStatus == done` (فقط `done`؛ `needs_review` و `failed` هرگز وارد پادکست نمی‌شوند بدون تصمیم رسمی مالک).
- حفظ کامل فیلترهای امنیتی: کتاب باید `BookStatus.ready` باشد (`is_student_visible_book`)، محدودیت پایه (کتاب پایهٔ بالاتر از دانش‌آموز → 422) و محدودیت زبان پشتیبانی‌شده — تست‌های آن‌ها بدون تغییر سبز ماندند.
- تست جدید `test_needs_review_pages_never_enter_podcast_sources`: صفحهٔ needs_review با متن وارد کتابخانهٔ منبع نمی‌شود، و بازه‌ای که فقط متن needs_review دارد با 422 رد می‌شود (پیش از ساخت هر job).

## ۳) چرخهٔ Job — **پوشش کامل با تست خودکار**

| وضعیت/رفتار | تست |
|---|---|
| `queued → … → completed` | `test_deep_dive_podcast_end_to_end` |
| هر ۴ قالب + prompt سفارشی | `test_all_four_formats_and_custom_prompt_reach_the_model` |
| `failed` (اسکریپت نامعتبر) + repair + retry | `test_failed_script_gets_one_repair_retry_then_retry_endpoint_succeeds` |
| **`cancelled`**: queued→cancel، generating_audio→cancel، retry→completed، cancel روی completed→422 | **تست جدید** `test_cancelled_episode_can_be_cancelled_retried_and_completed` |
| claim تکراری (دو worker) + `worker_lost` → recovery | `test_duplicate_job_claim_and_stale_recovery` |
| resume بدون re-synthesis قطعه‌های آماده | `test_audio_failure_resumes_without_re_synthesizing_ready_segments` |
| سقف job هم‌زمان (429) | `test_concurrent_job_limit_per_user` |
| ownership روی همهٔ endpointها | `test_ownership_is_enforced_on_every_endpoint` |

جلوگیری از اپیزود تکراری: claim اتمیک `queued → generating_script` با `rowcount` + سقف `max_concurrent_jobs`. اجرای real-condition لغو/تلاش مجدد روی staging API در فاز 04 انجام شده بود (cancel→200، retry→200، cancel روی failed→422 واقعی).

## ۴) Player — **UI verified** (روی صوت واقعی منتظر precondition)

- پخش/توقف/ادامه، سرعت (۰٫۷۵–۲×)، ±۱۵ ثانیه (assertion جدید: پس از پرش به بخش ۲ در ثانیهٔ ۲۱٫۲، دکمهٔ «−۱۵ ثانیه» نوار را به ۶ می‌برد — `aria-valuenow`)، انتخاب segment از timeline (پرش به start واقعی)، هایلایت متن همگام.
- **حفظ موقعیت هنگام جابه‌جایی صفحه:** تأیید با معماری و تست — `PodcastPlayerProvider` در ریشهٔ `app/layout.tsx:21-24` mount است؛ پلیر کوچک و `audio.currentTime` در ناوبری سمت کلاینت باقی می‌ماند (تست «plays through the global player»).
- **محدودیت ثبت‌شده:** پس از reload کامل صفحه، موقعیت بازیابی نمی‌شود (localStorage نداریم) — تصمیم با مالک.
- **پخش در پس‌زمینه:** رفتار بومی `HTMLAudioElement` در مرورگر است؛ در sandbox headless قابل اثبات نیست و در چک‌لیست دستی ماند. MediaSession/wake-lock پیاده نشده (پیشنهاد آینده).

## ۵) Regression کامل — همه سبز

| فرمان | نتیجه |
|---|---|
| `pytest tests/ -q` (کل backend) | **509 passed, 1 skipped** (فقط opt-in Postgres smoke بدون env) در 265s |
| همان skipped با `PHASE4_PG_URL` روی Postgres QA این فاز | **1 passed** — یعنی مجموعاً ۵۱۰/۵۱۰ |
| `vitest run` | **109 passed (13 فایل)** |
| `tsc --noEmit` | پاک |
| `eslint .` | پاک |
| `next build` (production) | موفق — شامل `/podcast` static |
| هیچ تستی حذف یا تضعیف نشد | ✓ فقط ۲ تست جدید + ۱ assertion جدید اضافه شد |

## ۶) یافتهٔ migration chain (بخش QA زیرساختی) — **یافته + اصلاح**

روی Postgres مستقل خالی (`/tmp/qa04a_pg:5433`, DB `darsyar_qa04a`، بدون هیچ تماسی با Production):

- `alembic upgrade head` → ۶۳ جدول ✓
- `alembic downgrade base` → جدول‌ها حذف می‌شوند اما **ENUMهای `book_status`/`page_status` orphan می‌مانند** → `upgrade head` بعدی با `type "book_status" already exists` می‌شکند.
- **اصلاح:** در `downgrade()` migration اولیه (`a04a943af8b1_initial.py`) دو `DROP TYPE IF EXISTS` اضافه شد (تنها دو enum کل زنجیره؛ مسیر upgrade و نصب تازه دست‌نخورده).
- بازآزمایی: downgrade → ۰ enum → re-upgrade → ۶۳ جدول + `alembic_version=a1b2c3d4e5f9` ✓ چرخهٔ کامل اثبات شد.

## ۷) فایل‌های تغییرکرده در این فاز

| فایل | تغییر |
|---|---|
| `backend/app/services/podcast_service.py` | منبع فقط صفحات `done` + docstring |
| `backend/alembic/versions/a04a943af8b1_initial.py` | پاک‌سازی enum در downgrade (reversibility) |
| `backend/tests/test_phase9_podcast.py` | +۲ تست (needs_review، lifecycle cancel/cancelled/retry) |
| `frontend/tests/PodcastWorkspace.test.tsx` | +assertion ±۱۵ ثانیه |
| `docs/REDESIGN_PHASE_04A_PODCAST_FINAL_QA.md` | همین سند |

## ۸) چک‌لیست دستی پس از فعال‌شدن Provider صوتی (برای مالک)

1. پادکست از کتاب ready بساز؛ progress باید مرحله‌به‌مرحلهٔ واقعی بالا برود (تولید متن → نوبت‌های صوت → ترکیب).
2. فایل نهایی را دانلود و در پلیر پخش کن؛ طول فایل با `duration_seconds` اپیزود یکی باشد.
3. زمان‌های segment را با صوت مقایسه کن (هیچ نوبت نباید از زمان نوبت بعد جلو بزند).
4. هایلایت متن در حین پخش را دنبال کن؛ seek/±۱۵/سرعت/انتخاب segment.
5. میانهٔ تولید، لغو کن → وضعیت «لغو شده» → تلاش مجدد → تکمیل.
6. پس از retry، فقط نوبت‌های ناتمام دوباره TTS شوند (cache بقیه حفظ شود).

## ۹) نتیجه

**`PARTIAL — UI VERIFIED, REAL AUDIO PENDING`** — همهٔ معیارهای غیرصوتی فاز با شواهد تست/کد اثبات شد؛ بخش صوت واقعی فقط با تنظیم Provider توسط مدیر مجاز قابل اجراست و تا آن زمان عمداً انجام‌نشده ثبت شد.
