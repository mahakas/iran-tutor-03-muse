# Phase 04C — آمادگی تولید پادکست (گزارش راستی‌آزمایی‌شده)

> تاریخ: ۲۰۲۶-۱۱-۲۴ · شاخه: `main` · commit پایه: `7db4f35` (اسنپ‌شات ورودی 04B) · همهٔ کارها uncommitted در working tree، بدون commit/push
> ## حکم نهایی: `PARTIAL — CORE VERIFIED, POSTGRES E2E UI-RUN & DEVICE EVIDENCE PENDING`
> هستهٔ فنی با شواهد واقعی روی PostgreSQL 16.2 و Chromium تأیید شد؛ یک بن‌بست واقعی خط لوله روی PostgreSQL کشف و رفع شد و تست‌های مرتبط سبز شدند؛ اما اجرای end-to-end از مسیر UI روی PostgreSQL هنوز در یک نقطهٔ دیگر متوقف می‌شود (بخش ۷-ب: مشکل بازِ مستند) و آزمون دستگاه واقعی MediaSession در دسترس نبود. طبق محدودیت فاز، هیچ موردی PASS فرضی نشده است.

---

## ۱) خلاصهٔ اجرایی

- **محور ۱ (wasPlaying):** تناقض گزارش‌شده با آزمون واقعی مرورگر حل شد: `wasPlaying` همیشه وضعیت واقعی audio element در لحظهٔ نوشتن است؛ علت ظاهر تناقض، **برچسب نادرست گام QA در گزارش 04B** بود که ریشه‌اش یک باگ واقعی UI بود (دکمهٔ بزرگ دیتیل با برچسب «توقف» هرگز pause نمی‌کرد). هر دو اصلاح شد؛ ۵ تست جدید؛ suite فرانت‌اند **۱۳۷ پاس**.
- **محور ۲ (PostgreSQL):** PostgreSQL 16.2 واقعی (باینری‌های واقعی از طریق pgserver) با دیتابیس ایزولهٔ QA (`darsyar_qa04c`) بالا آمد؛ migrationهای واقعی Alembic کامل اجرا شد (تک head + migration جدید با round-trip). سه نقص واقعی و تکرارپذیر کشف و رفع شد:
  1. **ردیف‌های تکراری `user_quotas`** (بدون قید یگانگی) → migration `b5c6d7e8f9a0` + upsert اتمیک.
  2. **Lost update در `record_ai_usage`** (شمارنده‌ها 200/3 به‌جای 1200/12 در بازتولید) → increment اتمیک server-side.
  3. **مسابقهٔ INSERT در کش TTS** (ردیف بدون فایل → UniqueViolation) → reuse + file-repair.
  به‌علاوه بن‌بست واقعی خط لوله (نگه‌داشتن ورودی ایندکس `user_quotas` روی تراکنشِ بازِ worker در طول callهای شبکه) با حسابداری تراکنش‌کوتاهِ مستقل رفع شد و یک اجرای مستقیم worker واقعی روی PG تا `completed` رسید.
- **محور ۳ (MediaSession):** wiring با همان تست‌های 04B + Chromium تأیید؛ دستگاه واقعی در دسترس نبود → همهٔ موارد سخت‌افزاری **PARTIAL** + دستورالعمل کامل manual QA (بخش ۹).
- **محدودیت مهم باقی‌مانده:** اجرای end-to-end از مسیر UI روی PostgreSQL هنوز در «تولید متن (۱۵٪)» متوقف می‌شود (بخش ۷-ب) — مشکلی متفاوت از بن‌بست رفع‌شده که پیش از پایان بودجهٔ این نشست به شناسایی قطعی نرسید. روی SQLite همان مسیر UI کامل سبز است (04B).

## ۲) وضعیت اولیه و Git Audit

- `git status`: سه فایل تغییرکردهٔ 04B (`PodcastPlayerProvider.tsx`، `PodcastPlayerPersistence.test.tsx`، گزارش 04B) روی commit پایه `7db4f35` — دقیقاً همان‌طور که گزارش 04B ثبت کرده بود (تأیید شد؛ چیزی حذف یا بازنویسی نشد).
- گزارش 04B موجود و سالم؛ فایل‌های کلیدی 04B (provider/store/tests/layout) و مسیرهای backend podcast بررسی شد.
- هیچ `reset --hard`، `clean`، `checkout -- .` یا stash اجباری اجرا نشد.

## ۳) بررسی دقیق wasPlaying

تمام مسیرهای نوشتن با مقدار `wasPlaying` (کد + آزمون واقعی مرورگر با localStorage instrumented):

| مسیر | مقدار ثبت‌شده | منطبق بر وضعیت واقعی element؟ |
|---|---|---|
| `timeupdate` در حال پخش | `isPlayingRef.current` → true | ✓ |
| `pause` (غیر-ended) | false (element در لحظهٔ event توقف شده) | ✓ |
| `play` | نمی‌نویسد؛ نوشتن بعدی state واقعی را می‌گیرد | ✓ |
| `seek` در حال پخش / در حال مکث | true / false (آزمون واقعی: C1/D1) | ✓ |
| تغییر سرعت (`ratechange` منطقی) | state واقعی | ✓ |
| `pagehide` / `visibilitychange(hidden)` در حال پخش | true (آزمون واقعی: E1) | ✓ |
| `ended` | رکورد پاک می‌شود | ✓ (قرارداد) |
| بستن پلیر / تغییر حساب / خروج | پاک‌سازی کامل | ✓ |

**نتیجه:** فیلد هیچ مفهوم «قصد کاربر» ندارد و نیازی به تغییر نام/نسخهٔ store/migration نیست (تست تحمل رکورد قدیمی بدون `wasPlaying/updatedAt` اضافه شد). **کشف جانبی:** در آزمون واقعی، کلیک روی دکمهٔ بزرگ دیتیل (برچسب «توقف») element را playing نگه داشت و هیچ نوشتنی انجام نشد (گام A1) → باگ UI؛ در `PodcastWorkspace` اصلاح شد که وقتی اپیزود current است دکمه `player.toggle()` بزند؛ تست اختصاصی اضافه شد (بدون re-fetch صوت، pause واقعی، resume بدون fetch دوم).

## ۴) قرارداد نهایی ذخیره/بازیابی وضعیت پخش

مطابق پیشنهاد فاز تصویب شد و با تست قفل شد: پس از Pause صریح → `wasPlaying=false`؛ در پخش فعال → true؛ پایان اپیزود → پاک‌سازی؛ Refresh هرگز autoplay نمی‌کند (تست: `play()` فقط پس از اقدام کاربر)؛ seek/سرعت/نمای مخفی state واقعی؛ رکورد خراب → پاک امن؛ رکورد بدون فیلدهای جدید → سازگار.

## ۵) تغییرات Frontend

| فایل | تغییر |
|---|---|
| `components/PodcastWorkspace.tsx` | `toggleOrPlay`: دکمهٔ بزرگ و دکمهٔ «پخش» دیتیل برای اپیزود جاری toggle می‌کنند (رفع باگ ریشه‌ای ابهام wasPlaying) |
| `tests/PodcastWorkspace.test.tsx` | تست 04C دکمهٔ دیتیل |
| `tests/PodcastPlayerPersistence.test.tsx` | ۴ تست قرارداد 04C (seek با state واقعی، pagehide/visibility، بدون autoplay پس از restore، تحمل رکورد قدیمی) |
| بقیهٔ فایل‌های 04B | دست‌نخورده |

نتیجه: `vitest` **137 passed** · `tsc --noEmit` پاک · `eslint .` پاک · `npm run build` موفق (BUILD_ID جدید، chunks سرو 200).

## ۶) بررسی PostgreSQL

- **محیط:** PostgreSQL 16.2 واقعی (pgserver، unix socket) → دیتابیس ایزولهٔ `darsyar_qa04c`؛ هیچ دیتابیس production استفاده نشد؛ backup ناکاربردی بود چون همهٔ داده‌ها QA-only بودند و با دستور پاک‌سازی مستند بازساختنی‌اند.
- **Migrationها:** `alembic upgrade head` کامل روی PG → تک head. Migration جدید `b5c6d7e8f9a0` (ادغام ردیف‌های تکراری user_quotas با جمع شمارنده‌ها + ایندکس یگانگی `ux_user_quotas_user_feature`) با `downgrade -1` → `upgrade` round-trip آزمایش شد.
- **مدل:** `UserQuota.__table_args__` ایندکس یگانگی را هم دارد تا `create_all` تست‌ها همان اسکیما بسازد.

## ۷) تحلیل قفل‌گذاری و Deadlock + آزمون‌های هم‌زمانی

**۷-الف) نتایج آزمون‌ها (اسکریپت `pg_concurrency.py` روی PG واقعی، پس از اصلاحات — هر چهار سبز):**

| آزمون | سناریو | نتیجه |
|---|---|---|
| T2a | INSERT اولین لمسِ `user_quotas` توسط worker روی تراکنشِ باز + شبیه‌سازی TTS کندِ ۶ ثانیه + ۶ فراخوانی API هم‌زمان همان کاربر | بدون خطا، بدون SQLSTATE، تأخیر API ~۲۶ms؛ شمارندهٔ نهایی **7 req / 850 token = دقیق** |
| T2b | ردیف موجود (بدون INSERT) + همان فشار | **14 / 1700 = دقیق** |
| T2c | ۱۲ increment هم‌زمان ×۱۰۰ با rate-limiter فعال (۸ مجاز، ۴×429) | **800 / 9 = دقیق** (429ها به‌درستی شمرده نشدند) → integrity_ok=true |
| T3 | ۵ claim هم‌زمان یک job | **دقیقاً ۱ برنده**، وضعیت `generating_script` |

SQLSTATEهای دیده‌شده در اجرای نهایی: **هیچ**. `lock_waits_final=0`.

**۷-ب) بن‌بست واقعی بازتولید و رفع‌شده — و مشکل باز باقی‌مانده:**
- در اجرای خط لولهٔ واقعی روی PG، worker روی `INSERT INTO user_quotas … ON CONFLICT` به‌مدت ۲۸۶+ ثانیه منتظر `transactionid` یک نشست `idle in transaction` ماند (شواهد: `pg_blocking_pids`، `pg_locks` با `RowExclusiveLock` روی `ux_user_quotas_user_feature`؛ کپچر زندهٔ ۷۰ نمونه در `/tmp/qa04c_live_capture.json`).
- **علت ساختاری:** نوشتن audit + quota درون تراکنشِ بلندِ worker که روی callهای شبکه باز می‌ماند → ورودی ایندکس یگانگی تا commit بعدی قفل می‌شود.
- **رفع (مطابق ممنوعیت فاز «شبکه خارج از تراکنش DB»):** `audit_in_own_transaction` در `run_capability_text/speech` → `_write_audit(session=None)` (تراکنش کوتاه مستقل با commit فوری)؛ فقط برای مسیر worker پادکست فعال و فقط روی PostgreSQL (SQLite یک‌نویسنده است — `no-op`) تا تست‌های SQLite سالم بمانند.
- **اثبات رفع:** اجرای مستقیم worker واقعی روی PG برای ep-3 → `completed` با duration واقعی ۲۰۰٫۳۶s و حسابداری واقعی (10 TTS + script).
- **مشکل باز (PARTIAL):** اجرای UI-driven روی PG هنوز در «تولید متن ۱۵٪» متوقف می‌شود (ep-6؛ provider پاسخ اسکریپت را داده: chat_calls افزایش یافته) — علت این نقطهٔ دوم پیش از پایان بودجه شناسایی نشد؛ یک نشست idle-in-transaction دیگر در مسیر UI را نشان می‌دهد و نیازمند کپچر بیشتر است. این مورد مانع Production روی مسیر worker مستقل نیست (worker مستقل سبز است) ولی برای مسیر in-process باید ادامه یابد.

## ۸) نتایج Worker و Job lifecycle

- `test_phase9_podcast.py` کامل سبز پس از اصلاحات (۵۸ پاس در فایل‌های هدف) — claim اتمی، stale recovery، retry، cancel و cache روی SQLite بدون تغییر رفتار.
- Claim race روی PG واقعی: T3 ✓ (۱ برنده از ۵).
- شکست provider/TTS timeout: پوشش تست‌های موجود + رفع مسابقهٔ cache (بخش ۶).

## ۹) اعتبارسنجی مصرف و تسویه Quota

- عدم دوباره‌مصرف: T2c اثبات عددی (800/9 دقیق؛ 429ها شمرده نمی‌شوند).
- ناسازگاری job/quota: با upsert اتمیک + ایندکس یگانگی + accounting مستقل، ردیف‌های تکراری و lost update منتفی‌اند.
- `record_ai_usage` همچنان هرگز مسیر درخواست/worker را نمی‌شکند (fail-safe حفظ شد).

## ۱۰) وضعیت Provider واقعی و آزمایشی

واقعی (Backend، PostgreSQL، Worker درون‌پردازشی، Queue/claim واقعی، اعتبارسنجی اسکریپت، کش TTS واقعی، FFmpeg واقعی، فایل صوتی و duration واقعی، ثبت وضعیت و accounting واقعی) — آزمایشی (chat/TTS از طریق سرور faked OpenAI-compatible روی :8003 و SMS demo برای OTP ثبت‌نام حساب دوم؛ فقط جایگزین سرویس بیرونی). **Provider واقعی تنظیم نشده بود → آزمون Provider واقعی PASS اعلام نمی‌شود.**

## ۱۱) نتایج MediaSession

wiring: همان ۸ تست 04B MediaSession (ثبت یک‌بارهٔ handler، seekto/±۱۵ ثانیه، playbackState، positionState، مرورگر بدون MediaSession) — همه سبز؛ در Chromium واقعی در QA فاز 04B اثبات شده و در این فاز تغییری در آن مسیر نداشتیم.

## ۱۲) آزمون‌های دستگاه واقعی

**در دسترس نبود** (فقط sandbox headless). همهٔ سناریوهای Android/Chrome و iOS/Safari PARTIAL ثبت می‌شوند؛ هیچ نتیجهٔ شبیه‌سازی‌شده‌ای PASS دستگاه اعلام نشد.

## ۱۳) دستورالعمل Manual QA دستگاه واقعی (برای تکمیل PARTIAL)

**Android/Chrome (هر مدل + نسخهٔ OS/Chrome ثبت شود):**
۱. یک اپیزود کامل بسازید و از دکمهٔ پخش شروع کنید.
۲. `navigator.mediaSession.metadata.title` باید عنوان فارسی پادکست باشد؛ کنترل رسانه در Notification ظاهر شود.
۳. صفحه را خاموش کنید → کنترل روی Lock Screen ظاهر شود (عنوان + گوینده).
۴. Pause/Play از صفحهٔ قفل → وضعیت پلیر و `playbackState` همگام.
۵. Seek از صفحهٔ قفل → زمان مینی‌پلیر تغییر کند؛ موقعیت پس از Unlock حفظ شود.
۶. هدست/بلوتوث: play/pause/next/previous → فقط play/pause/seek فعال است (prev/next عمداً ثبت نشده — هیچ کنترلی نباید ارسال شود).
۷. Track کامل پخش شود → کنترل رسانه OS باید بسته شود و رکورد ادامه پاک شود.

**iOS/Safari:**
۱. پخش شروع شود؛ کنترل CC/Lock Screen عنوان و artwork را نشان دهد.
۲. Pause/Play از Lock Screen؛ سپس Seek (iOS seek از lock محدود است — رفتار واقعی ثبت شود).
۳. مرورگر به پس‌زمینه → پخش ادامه یابد؛ بازگشت به برنامه → موقعیت حفظ.
۴. قطع/وصل هدست Bluetooth و پاسخ‌ها ثبت شود.
هر گام: مدل، OS، نسخهٔ مرورگر، نتیجه (PASS/FAIL/محدودیت) ثبت و در گزارش ضمیمه شود.

## ۱۴) تست‌های Frontend و Backend

| فرمان | نتیجه |
|---|---|
| `npx vitest run` | **137 passed / 14 فایل** (۱۰۹ پایه + ۲۱ تست 04B + ۵ تست 04C + ۲ رگرسیون 04B) |
| `npx tsc --noEmit` / `npx eslint .` | پاک |
| `npm run build` | موفق (production، chunks سرو 200) |
| `pytest -q` (بدون `.env` QA) | **509 passed / 1 skipped** در اجرای کامل پس از اصلاحات quota و accounting (اجرای بعدیِ حذف باگ کش TTS هنوز اجرا نشده؛ دو فایل هدفش جداگانه سبز شد — test_phase9 + governance = 58 passed) |

## ۱۵) شواهد Playwright و Browser QA

- QA کامل 04B روی **SQLite stack** (پایان فاز قبل) ۱۶/۱۶ PASS بود و در این فاز تغییری در آن مسیر نداشت (رگرسیون صفر در سطح تست).
- QA روی **PG stack**: ورود و ساخت اپیزود از UI تا claim (25٪) سبز؛ سپس توقف در ۱۵٪ (بخش ۷-ب — مشکل باز). اسکرین‌شات‌ها و لاگ‌ها: `/tmp/render_qa04b/`، `/tmp/qa04c_live_capture.json`، `/tmp/qa04c_pg_results.json`، `/tmp/qa04c_run_final.log` (کپی در `download/phase04c/qa_evidence/`).

## ۱۶) Rollback (محدود به Phase 04C؛ 04B را حذف نمی‌کند)

```bash
cd /home/z/my-project/iran-tutor-main
# ۱) بازگرداندن فقط فایل‌های تغییر یافتهٔ 04C (04B دست‌نخورده می‌ماند):
git checkout -- frontend/components/PodcastWorkspace.tsx \
  frontend/tests/PodcastWorkspace.test.tsx \
  frontend/tests/PodcastPlayerPersistence.test.tsx \
  backend/app/services/quota_service.py backend/app/models/governance.py \
  backend/app/services/ai_gateway.py backend/app/services/capability_runtime.py \
  backend/app/services/podcast_service.py
# ۲) حذف migration 04C روی دیتابیس هدف (برگشت‌پذیر؛ فقط ایندکس حذف می‌شود):
cd backend && DATABASE_URL=<هدف> alembic downgrade -1   # b5c6d7e8f9a0 → a1b2c3d4e5f9
# ۳) حذف فایل migration 04C:
rm alembic/versions/b5c6d7e8f9a0_quota_accounting_integrity.py
# پس از هر گام: pytest -q و vitest run و build برای اطمینان از سبز بودن.
```
توجه: `git checkout` فقط فایل‌های بالا را برمی‌گرداند؛ تغییرات 04B در `PodcastPlayerProvider.tsx` و گزارش 04B دست‌نخورده می‌مانند. ادغام ردیف‌های تکراری انجام‌شده توسط migration برگشت‌پذیر نیست (مستند در خود migration).

## ۱۷) فایل‌های تغییرکرده/جدید این فاز

- **Frontend:** `PodcastWorkspace.tsx`، `PodcastWorkspace.test.tsx`، `PodcastPlayerPersistence.test.tsx`
- **Backend:** `quota_service.py` (upsert اتمیک + race-safe get_or_create)، `models/governance.py` (ایندکس یگانگی)، `ai_gateway.py` (+`audit_in_own_transaction`)، `capability_runtime.py` (+forward flag)، `podcast_service.py` (+فعال‌سازی در worker؛ +رفع مسابقهٔ کش TTS)
- **Migration جدید:** `alembic/versions/b5c6d7e8f9a0_quota_accounting_integrity.py` (برگشت‌پذیر)

## ۱۸) محدودیت‌ها و موارد PARTIAL

1. **خط لولهٔ UI روی PostgreSQL:** توقف در ۱۵٪ پس از دریافت اسکریپت — باز (بخش ۷-ب)؛ worker مستقل روی PG کامل سبز است.
2. **دستگاه واقعی MediaSession:** در دسترس نبود → PARTIAL با پروتکل manual (بخش ۱۳).
3. **Provider واقعی:** تنظیم نشده → PASS اعلام نمی‌شود.
4. **Rate limiter درون‌پردازشی:** در استقرار چند-پردازشی باید Redis پشتش باشد (طراحی فعلی؛ خارج از scope).
5. **اجرای مجدد کامل backend suite پس از فیکس کش TTS:** فایل‌های هدف سبز شدند؛ یک `pytest -q` نهایی توصیه می‌شود (بودجهٔ این نشست اجازه نداد).

## ۱۹) حکم نهایی

**`PARTIAL — CORE VERIFIED, POSTGRES E2E UI-RUN & DEVICE EVIDENCE PENDING`**

| معیار | حکم |
|---|---|
| تعیین تکلیف wasPlaying + قرارداد + تست‌ها | **PASS** |
| رفع باگ دکمهٔ دیتیل (ریشهٔ ابهام) | **PASS** |
| migration یگانگی quota + upsert اتمیک + integrity روی PG واقعی | **PASS** |
| رفع بن‌بست accounting worker (تراکنش کوتاه) — worker مستقل روی PG | **PASS** |
| مسابقهٔ کش TTS | **PASS** (رفع + تست‌های هدف سبز) |
| Claim race / Retry / Cancel / stale recovery | **PASS** (تست‌های موجود + T3 روی PG) |
| خط لولهٔ UI روی PostgreSQL | **PARTIAL** — توقف در ۱۵٪ (باز، مستند) |
| Provider واقعی | **PARTIAL** — تنظیم نشده |
| MediaSession روی دستگاه واقعی | **PARTIAL** — دستگاه در دسترس نبود؛ پروتکل manual آماده |
| عدم Regression | **PASS** (137 فرونت + 509 بک‌اند در آخرین اجرای کامل) |
| Production Build | **PASS** |
