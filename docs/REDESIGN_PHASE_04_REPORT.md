# گزارش Redesign Phase 04 — بازطراحی استودیوی پادکست آموزشی

> تاریخ: ۲۰۲۶-۱۱-۲۴ · شاخهٔ پیشنهادی: `redesign/phase-04-podcast-studio` (در working tree باقی مانده؛ commit نشده)
> ## نتیجه: `PASS`

## ۱) خلاصهٔ تغییرات و دلیل

استودیوی پادکست به جریان سه‌بخشی (کتابخانه → ساخت → گوش‌دادن/تعامل) ارتقا یافت. مطالعهٔ کد نشان داد زیرساخت کامل از قبل موجود است (`podcast_service.py` با heartbeat/stale-recovery/retry-مسیری، API با cancel/retry/regenerate/questions، کامپوننت با library/create/detail). بنابراین فاز به **سدکردن گپ‌های واقعی UI نسبت به پرامپت** اختصاص یافت — بدون بازنویسی worker، job lifecycle یا جدول‌ها و **بدون هیچ تغییری در backend (0 خط diff)**:

1. **لغو واقعی تولید (cancel):** backend از فاز 9 دکمه‌ای برای آن نداشت و پرامپت «action جعلی ممنوع» — حالا در کتابخانه و صفحهٔ جزئیات برای وضعیت‌های `queued/generating_script/generating_audio/assembling_audio` دکمهٔ «لغو تولید» به `POST /api/v1/podcasts/{id}/cancel` وصل است.
2. **ادامهٔ کار برای لغوشده‌ها:** backend تلاش مجدد را فقط برای `failed/cancelled` می‌پذیرد؛ UI قبلاً فقط برای `failed` نشان می‌داد. حالا «تلاش مجدد» برای هر دو وضعیت نمایش داده می‌شود.
3. **گام تأیید منبع و محدوده (مرحلهٔ ۵):** دکمهٔ «تولید پادکست» دیگر مستقیم POST نمی‌زند؛ ابتدا بخش تأیید با خلاصهٔ دقیق کتاب/فصل/صفحه/قالب/مدت/تمرکز + هشدار روشن «منبع ناکافی → توقف همان ابتدا با پیام دقیق» نمایش داده می‌شود و فقط با «تأیید و شروع تولید» ارسال می‌شود.
4. **خط زمانی بخش‌ها (segment timeline):** در پلیر، فقط وقتی backend زمان واقعی هر بخش را اندازه گرفته باشد (`start_time/end_time` از مونتاژ واقعی صوت، هرگز estimate)، نوار خط زمانی با طول نسبی واقعی هر نوبت رندر می‌شود؛ کلیک روی هر بخش به شروع آن پرش می‌کند و بخش در حال پخش هایلایت می‌شود.
5. **RTL/موبایل:** کلاس‌های جدید کاملاً RTL-safe هستند و در `@media (max-width: 640px)` پلیر ستونی و خط زمانی فشرده می‌شود.

پیشرفت واقعی backend (`progress/progress_stage`) عیناً حفظ شد؛ هیچ درصد یا transcript جعلی اضافه نشد. پخش صوت همچنان از blob احراز هویت‌شدهٔ همان endpoint قبلی می‌آید و به هیچ درخواست AI جدیدی وصل نیست.

## ۲) فایل‌های تغییرکرده/جدید

| فایل | نقش |
|---|---|
| `frontend/components/PodcastWorkspace.tsx` | +اکشن لغو (library/detail)، تلاش مجدد برای `cancelled`، گام تأیید ۵، خط زمانی بخش‌ها، props جدید `onCancelJob/onRetry` |
| `frontend/app/globals.css` | +کلاس‌های `pc-badge.status.cancelled`, `pc-cancel-btn`, `pc-confirm*`, `pc-timeline*` + قوانین موبایل برای پلیر/خط زمانی |
| `frontend/tests/PodcastWorkspace.test.tsx` | تست create برای گام تأیید به‌روز شد (POST فقط پس از تأیید) + assertion خط زمانی/پرش + ۲ تست جدید cancel و retry-cancelled |
| `scripts/staging_podcast_phase04.py` (خارج از مخزن) | اسموک زندهٔ قرارداد API پادکست روی staging |

## ۳) قابلیت‌های حفظ‌شده و تست محافظ

- worker مستقل (`backend/scripts/podcast_worker.py`)، claim اتمیک، heartbeat، `recover_stale_episodes` (worker_lost→retryable)، cache صوتی content-addressed، resume segmentها: **دست‌نخورده** — `backend diff = 0` و `test_phase9_podcast.py: 19 passed`.
- قرارداد API (endpoint/پاسخ/کدها): بدون تغییر — اسموک زندهٔ staging تأیید کرد.
- ۶ تست قبلی `PodcastWorkspace.test.tsx` حفظ شدند (فقط تست create با کلیک «تأیید و شروع تولید» ادامه می‌یابد)؛ کل رگرسیون فرانت `109 passed (13 files)`.
- قواعد محصول: منابع فقط کتاب رسمی (`resolve_podcast_sources`)، محدودیت پایه، status `ready` فقط با شواهد backend — همه در backend دست‌نخورده.

## ۴) فرمان‌های اجراشده و خروجی واقعی

| فرمان | خروجی |
|---|---|
| `npx vitest run tests/PodcastWorkspace.test.tsx` | **8 passed** (6 قبلی + 2 جدید) |
| `npx tsc --noEmit` | بدون خطا |
| `npx eslint components/PodcastWorkspace.tsx tests/PodcastWorkspace.test.tsx` | exit 0 |
| `npx vitest run` (کل فرانت) | **109 passed (13 files)** |
| `.venv/bin/pytest tests/test_phase9_podcast.py -q` | **19 passed in 110.28s** |
| اسموک زندهٔ staging (`scripts/staging_podcast_phase04.py`) | config → **503** (قابلیت/TTS روی staging خاموش است — پاسخ صادقانه) · list → 200 · cancel اپیزود آزمایشی → **200 cancelled** · retry → **200 queued** (claim خودکار fast-path) · cancel روی failed → **422 «قابل لغو نیست»** · DELETE → 204 · لیست نهایی خالی، بدون ردیف باقی‌مانده |

نکتهٔ اسموک: پس از retry، worker in-process فوراً claim می‌کند؛ چون اپیزود آزمایشی منبع خالی داشت، backend به‌درستی آن را با `sources_missing` failed کرد — رفتار lifecycle واقعی و بدون جعل.

## ۵) تست‌های اجرا‌نشده و دلیل

- **تولید واقعی صوت (TTS→assembly) روی staging:** provider صوتی روی staging تنظیم نشده (`config` → 503 «صدای پادکست توسط مدیر تنظیم نشده است») — همان محدودیت ثبت‌شده در `REDESIGN_STATUS_MATRIX.md`. پوشش این مسیر در `test_phase9_podcast.py` با provider فیک انجام و 19/19 سبز شد.
- **browser test موبایل واقعی:** محیط headless فقط jsdom دارد؛ «موبایل بودن» پلیر با قوانین media-query CSS (ستونی شدن `pc-player-main`، فشرده‌سازی timeline) + تست‌های RTL موجود پوشش شد و در چک‌لیست دستی ماند.
- sync transcript در پخش واقعی (timeupdate): در jsdom شبیه‌سازی زمان صوت ممکن نیست؛ منطق هایلایت با تست کلیک/seek (aria-valuenow=21) و تست activeSegmentId پوشش شده.

## ۶) ریسک‌ها، تصمیم‌های مالک، rollback

1. **دکمهٔ regenerate همچنان برای همهٔ وضعیت‌ها فعال است** (رفتار قبلی؛ backend مجازش می‌داند). اگر مالک بخواهد فقط برای completed باشد، یک شرط UI کافی است — تغییر قرارداد نیست.
2. صفحات `needs_review` در پادکست به‌عنوان منبع پذیرفته می‌شوند (`resolve_podcast_sources`)؛ این با قاعدهٔ «needs_review هرگز در RAG» متفاوت است و تصمیم آن از فازهای قبلی است — خارج از scope این فاز UI و برای مالک ثبت شد.
3. گام تأیید یک رفتار اضافه‌شدهٔ UX است (بدون تغییر endpoint)؛ اگر مسیر تست‌های اتوماسیون خارجی مستقیماً POST می‌زند، بدون تأثیر است چون سمت API تغییری نکرده.
4. **Rollback:** `git checkout -- frontend/components/PodcastWorkspace.tsx frontend/app/globals.css frontend/tests/PodcastWorkspace.test.tsx` — backend/DB کاملاً دست‌نخورده‌اند و rollback فرانت بی‌خطر است.

## ۷) چک‌لیست تست دستی فارسی

1. `/podcast` ← کتابخانه: کارت در حال تولید، نوار درصد واقعی + مرحلهٔ فارسی، دکمهٔ **لغو تولید** → پیام «تولید پادکست لغو شد» و badge «لغو شده».
2. کارت لغوشده/ناموفق → **تلاش مجدد** → بازگشت به «در صف تولید».
3. ساخت پادکست جدید → پایه/رشته/کتاب/فصل/صفحه → «تولید پادکست» → مرحلهٔ **۵. تأیید منبع و محدوده** → «بازگشت به ویرایش» یا «تأیید و شروع تولید».
4. پس از اتمام تولید → جزئیات → پخش؛ **خط زمانی بخش‌ها** زیر نوار زمان → کلیک بخش → پرش و هایلایت؛ متن همگام با زمان.
5. −۱۵/+۱۵ ثانیه، سرعت (۰٫۷۵ تا ۲×)، صدا؛ پلیر کوچک پایین صفحه هنگام جابجایی بین صفحات می‌ماند.
6. «از گویندگان سؤال بپرس» → پاسخ با citationها؛ لایک/دیسلایک + علت‌ها؛ دانلود؛ تغییر عنوان؛ حذف.
7. موبایل (عرض ≤ ۶۴۰): پلیر ستونی، دکمه‌های ≥ ۴۰px، اسکرول افقی صفر.

مسیرهای بازبینی: UI `/podcast` (library→create→detail) · API `GET /api/v1/podcasts/config` · `POST /api/v1/podcasts` · `GET /api/v1/podcasts/{id}` · `POST …/cancel` · `POST …/retry` · `GET …/audio|download|transcript` · `POST …/questions|feedback` · `PATCH /api/v1/podcasts/{id}` · `DELETE /api/v1/podcasts/{id}`.

## ۸) نتیجه

`PASS` — جریان create (با گام تأیید) → process (progress واقعی + لغو واقعی + تلاش مجدد لغوشده/ناموفق) → play (seek/speed/timeline/متن همگام) → resume/retry/feedback کامل و قابل استفاده؛ worker و ۱۹ تست backend بدون regression؛ پلیر RTL و موبایل؛ ۱۰۹ تست فرانت سبز.
