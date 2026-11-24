# PHASE 00-A — گزارش بازبینی نهایی Patch

> **تاریخ:** ۲۰۲۶-۱۱-۲۳ · **دامنه:** بازبینی کیفیت، ایمنی و حفظ رفتارِ تغییرات فاز ۰۰-A پیش از تأیید فاز ۱
> **نتیجهٔ نهایی: `PASS — READY FOR PHASE 01`** (استدلال در بند ۹)
> **هیچ commit، push یا merge انجام نشده است.**

---

## ۱. تأیید changeset — دقیقاً ۱۵ فایل

`diff -rq` درخت کار در برابر آرشیو پایه (`iran-tutor-hotfix-auto-publish.zip`) با حذف آرتیفکت‌های build، دقیقاً ۱۵ ورودی دارد و هیچ چیز دیگری:

- کد: `README.md` · `backend/alembic/versions/e1f2a3b4c5d6_…py` (جدید) · `backend/tests/test_phase4_postgres_smoke.py` · ۷ کامپوننت `frontend/components/` (MistakeBankWorkspace، ChatRecycleBin، ImmersiveReader، AuthFlowModal، AdminUsersPanel، StudentApp، BookGradePicker)
- مستندات: ۳ سند فاز ۰۰ + `REDESIGN_DECISIONS_LOG.md` (جدید) + `REDESIGN_PHASE_00A_REPORT.md` (جدید)

کل diff یکپارچه (۶۱۵ خط) سطربه‌سطر خوانده شد؛ یافته‌ها در بندهای ۲ تا ۵.

## ۲. بازبینی اصلاحات ESLint در ۷ کامپوننت — race / stale / cleanup / props / تعویض سریع

| کامپوننت | سناریوی بررسی | یافته |
|---|---|---|
| **StudentApp** (books/fields) | تعویض سریع پایه/شاخه/رشته | هر run یک `AbortController` اختصاصی دارد که در cleanup با `controller?.abort()` لغو می‌شود؛ پاسخ‌های در-وضعیت با `if (cancelled) return` **پس از** `response.json()` هم نگه داشته می‌شوند. تفاوت با کد قدیمی: اگر deps پیش از رسیدن پاسخ عوض شود، run جدید قبل از ساخت controller لغو می‌شود → **هیچ درخواست یتیمی ساخته نمی‌شود**؛ و اگر پاسخ کامل رسیده ولی run کهنه شده باشد، اعمال نمی‌شود (کد قدیمی در این حالت پاسخ stale را اعمال می‌کرد — رفع یک race از قبل موجود، نه ایجاد تفاوت رفتاری). خطای `AbortError` بی‌صدا؛ JSON معیوب همان مسیر خطای قبلی. |
| **BookGradePicker** (۳ effect) | همان تعویض سریع + مسیرهای failure | همان الگوی StudentApp؛ resetهای سینک قدیمی (پایه‌های ۱-۹ و شاخهٔ خالی) عیناً در IIFE حفظ شده‌اند؛ مسیرهای catch با `if (!cancelled)` محافظت شده‌اند (کد قدیمی می‌توانست پس از شروع run جدید، state تازه را با reset کهنه بازنویسی کند — باز هم سخت‌گیرتر از قبل). **ریست‌های اصلی رویداد-محور از قبل در handlerها بودند و دست‌نخورده‌اند.** |
| **ImmersiveReader** (۲ effect) | تعویض سریع کتاب/صفحه | reset پنج‌گانهٔ کتاب و reset صفحه/تصویر عیناً در IIFE؛ ترتیب تضمین‌شده: microtaskهای run جدید همیشه قبل از اولین پاسخ شبکه اجرا می‌شوند → resetِ کتاب جدید قبل از دورانداختن پاسخ کتاب قدیمی. `objectUrl` پس از revoke در cleanup همانند قبل؛ حالت «لغو قبل از ساخت objectUrl» هم بدون leak است. وابستگی‌ها (`authFetch, bookId` / `authFetch, bookId, overview, pageIndex`) بدون تغییر. |
| **AuthFlowModal** | باز/بسته شدن، تغییر notice حین باز بودن | ریست فرم عیناً (۱۲ setter با همان ترتیب) با `if (cancelled)`؛ تغییر notice حین باز بودن همانند قبل کل فرم را ریست می‌کند (notice در deps مانده). تایمر فوکوس در cleanup پاک می‌شود + محافظ جدید: فوکوس فقط وقتی کاربر فیلدی را شروع نکرده — رفع باگ دزدیدن فوکوس (تغییر رفتاری مثبتِ مستندشده؛ هدف تست «drop نشدن ورودی» را محقق‌تر می‌کند). |
| **ChatRecycleBin** | تب bin، خطای شبکه | بدنهٔ `loadBin` عیناً inline شد (تک-مصرف‌کننده بود — بدون کپی منطق)؛ `setBusy(true)` → `finally setBusy(false)` بدون شرط، مثل قبل؛ deps معادل (`[tab, authFetch, en]` به‌جای `[tab, loadBin]`). در-وضعیت بودن fetch هنگام تعویض تب، همانند قبل بدون لغو است (پاسخ آخر می‌برد و فقط تب bin مصرفش می‌کند) — **رفتار از قبل موجود، نه رگرسیون**. |
| **MistakeBankWorkspace** | تغییر فیلتر | فقط wrap شدن `void load()`؛ منطق و deps (`[load]`) دست‌نخورده؛ guard ترتیبی داخل `load` با `loadSeq`… در پنل ادمین مشابه است و اینجا آخرین پاسخ برنده می‌شود — همان رفتار قبل. |
| **AdminUsersPanel** | تغییر فیلترها/صفحه‌بندی | هر دو effect فقط deferred؛ `load` خودش با `loadSeq.current` ریس پاسخ‌های stale را می‌گیرد (از قبل موجود)؛ syncِ URL بدون setState و بدون تغییر sync می‌ماند؛ disable خطیِ از قبل موجود حفظ شد. |

**جمع‌بندی بند ۲:** هیچ مسیر پاسخ-stale جدیدی ایجاد نشده؛ در دو نقطه (StudentApp books، BookGradePicker catchها) برعکس، مسیرهای stale ضعیف‌تر از قبل **سخت‌گیرانه‌تر** شده‌اند. cleanupها کامل‌تر شدند (controller یتیم ندارد، objectUrl/timer همانند قبل). تغییر props و تعویض سریع در هر سه الگو (abort-based، cancelled-flag، deferred-reset) پوشش داده شد.

## ۳. آیا async-IIFE + microtask «دور زدن lint» است؟

**خیر — اما بند مهمی از صداقت فنی دارد که صریح مستند می‌شود:**

- **دستهٔ الف — اثرِ صرفاً تحلیلی (MistakeBank، AdminUsersPanel×۲):** در کد اصلی این effectها **هیچ setState هم‌زمانی وجود نداشت** (تمام setStateهای `load`/`loadRoles` بعد از await خودشان رخ می‌دهند). قاعدهٔ `set-state-in-effect` نمی‌تواند مرز await را از طریق ارجاع به یک `useCallback` ردیابی کند، پس هر فراخوانیِ effect→تابع‌محلیِ دارای setState را هم‌زمان می‌داند. wrap شدن، فقط همین کورسوی تحلیل را باز می‌کند؛ دلتای رفتاری صفر است. راه‌حل کاملاً «اصولی‌تر» این دسته، inline کردن منطق fetch درون effect (الگوی `MasteryWorkspace`) بود — برای ChatRecycleBin (تک-مصرف‌کننده) همین کار انجام شد؛ برای این سه مورد نشد چون `load`/`loadRoles` توسط handlerهای رویداد هم صدا زده می‌شوند و inline شدن یعنی کپی ~۲۵ خط منطق تجاری (ریسک تکرار و واگرایی آینده).
- **دستهٔ ب — resetهای واقعاً سینک (ChatRecycleBin busy، ImmersiveReader، AuthFlowModal، guardهای StudentApp/BookGradePicker):** اینجا setState واقعاً هم‌زمان بود. تأخیر یک microtask آن را از «کاسکاد سینک داخل پاس کامیت» خارج می‌کند — دقیقاً همان چیزی که قاعده هدف می‌گیرد؛ چون effectها بعد از paint اجرا می‌شوند و microtask قبل از paint بعدی تمام می‌شود، **هیچ محتوای کهنه‌ای paint نمی‌شود و توالی reset→fetch عیناً حفظ می‌شود**. صادقانه: این الگو تعداد کل رندرها را کم نمی‌کند؛ فقط کاسکاد سینکِ درون کامیت را می‌شکند — یعنی «معالجهٔ هدفمندِ همان نشانه‌ای که lint می‌گیرد»، نه حذف کامل setState از effect.
- **راه‌حل‌های اصولی‌تر و اینکه چرا در این فاز نشد** (برای فازهای بازطراحی UI):
  1. **ریست رویداد-محور** — از قبل در BookGradePicker/StudentApp برای مسیرهای کاربر-محور موجود است؛ قسمت باقی‌مانده مسیرهای غیر-رویدادی است (mount اولیه و بازیابی خطای fetch) که handler ندارند.
  2. **render-adjust با مقایسهٔ مقدار قبلی** (الگوی رسمی React برای تغییر prop) — جایگزین درست برای reset کتاب در ImmersiveReader و ریست فرم AuthFlowModal؛ اما در نسخهٔ فعلی پیکربندی، خطر فعال‌شدن قواعد هم‌خانوادهٔ react-compiler روی setState در render و دلتای رفتاری بیشتر را داشت و با مأموریت «بدون تغییر غیرضروری رفتار» فاز ۰۰-A در تعارض بود.
  3. **remount با `key`** — برای AuthFlowModal ممکن بود، اما تغییر notice حین باز بودن مودال (مثلاً پس از درخواست OTP) با remount از دست می‌رفت؛ رد شد.
  4. **الگوی derive** (مثلاً نگه‌داشتن `detailPage` کنار `detail` در ImmersiveReader و مشتق‌کردن نمایش) — refactor واقعی با ریسک رفتاری بیشتر؛ به فاز بازطراحی موکول شد.
  5. **لایهٔ دادهٔ بیرونی (TanStack Query و مانند آن)** — تغییر وابستگی/معماری؛ خارج از صلاحیت این فاز.

**نتیجه:** الگوی انتخاب‌شده حداقل-تغییر، رفتار-محافظ و شفاف‌مستند است؛ جایگزین‌های اصولی‌تر شناسایی و برای فاز بعدی ثبت شد تا این الگو به «عادت دائمی» تبدیل نشود.

## ۴. بازبینی عملی Migration `e1f2a3b4c5d6` — ۱۶/۱۶ سنجهٔ واقعی روی PostgreSQL

بازبینی ایستا: فایل migration فقط `alter_column` عرض (64↔36) با محافظ `_is_postgres()` به الگوی phase-7 است؛ بدون دست‌کاری جدول/ردیف/ایندکس؛ head جدید با `down_revision = d0e1f2a3b4c5` (زنجیره خطی می‌ماند).

آزمون عملی (`scripts/review_migration_e1f2a3b4c5d6.py` روی PostgreSQL واقعی pgserver با pgdata دورریز و حذف‌شدنی) — **ALL_OK ۱۶/۱۶**:

| سنجه | نتیجه |
|---|---|
| schema پیش از migration (`upgrade d0e1f2a3b4c5`) | ✅ عرض ستون = `64` |
| **بررسی دادهٔ موجود قبل از محدودکردن** | ✅ seed یک user واقعی (UUID ۳۶ کاراکتری) + deck + study session؛ `max(length(user_id))=36` و `max(length(id)) در users=36` — FK به `users.id varchar(36)` تضمین ساختاری است و عملاً هم تأیید شد |
| **عدم امکان truncate خاموش** (کاوش منفی) | ✅ INSERT با `user_id` چهل‌کاراکتری توسط DB رد شد → ۰ ردیف با طول >۳۶؛ یعنی narrowing هرگز داده را نمی‌بُرد یا یا خطای تمیز می‌دهد |
| `upgrade head` | ✅ اعمال `e1f2a3b4c5d6`؛ عرض → `36` |
| عدم از دست رفتن داده | ✅ ۱ ردیف پابرجا؛ join ردیف به user سالم |
| `downgrade -1` | ✅ عرض → `64`؛ ردیف سالم |
| بازاعمال `upgrade head` | ✅ عرض → `36` |
| `current` | ✅ `e1f2a3b4c5d6 (head)` |
| `heads` | ✅ دقیقاً یک head (زنجیره خطی، بدون انشعاب) |
| `alembic check` | ✅ تمیز (No new upgrade operations) |

**سازگاری PostgreSQL:** `ALTER COLUMN … TYPE varchar(36)` با DDL تراکنشی؛ سابقهٔ همین عملیات در `d4e5f6a7b8c9` (فاز ۷) روی PostgreSQL راستی‌آزمایی شده بود و اینجا هم بر بستر واقعی اجرا شد. **حفظ وضعیت head:** head از `d0e1f2a3b4c5` به `e1f2a3b4c5d6` منتقل شد (تغییر مداوم و برگشت‌پذیر با `downgrade -1`) — مستند در گزارش ۰۰-A بند ۸.

## ۵. مقایسهٔ `test_phase4_postgres_smoke.py` — هیچ assertion حذف/تضعیف نشده

مقایسهٔ صوری خطوط `assert` بین نسخهٔ آرشیو و فعلی: **۴/۴ assertion عیناً یکسان** (`len(grades)>=2`، `strict=={11}`، `any(grade==12)`، `ids[10] and ids[12]`) — فقط شمارهٔ خط‌ها به‌خاطر کامنتِ اضافه‌شده جابه‌جا شده. تنها تغییر: افزودن پارامتر `book_ids` به سه فراخوانی (همان کتاب‌های ready که خود تست می‌سازد) طبق قرارداد قفل‌شدهٔ فاز ۱۰ + کامنت. کل بدنهٔ تست (seed، monkeypatchها، `no_vectors`، teardown با drop_all) دست‌نخورده است.

## ۶. اجرای مجدد تست‌های رگرسیون و Build

| gate | فرمان | نتیجهٔ این اجرا |
|---|---|---|
| Backend pytest | `.venv/bin/python -m pytest -q tests` | ✅ **۴۶۸ passed / ۱ skipped / ۲ warnings** در 196.17s — exit 0 |
| Vitest | `npm test` | ✅ **۵ فایل، ۳۹/۳۹** — exit 0 |
| ESLint | `npm run lint` | ✅ **۰ خطا / ۰ هشدار** — exit 0 |
| Build | `npm run build` | ✅ **Compiled successfully in 8.6s** — exit 0 |
| Migration suite (PG واقعی) | `scripts/review_migration_e1f2a3b4c5d6.py` | ✅ **ALL_OK ۱۶/۱۶** (بند ۴) |

## ۷. فایل‌های خارج از changeset — بدون تغییر

`diff -rq` نهایی درخت در برابر آرشیو: **دقیقاً ۱۵ ورودی (صفر ورودی بیرون از changeset)**؛ صفر تفاوت در `storage/` — PDF دموی بازتولیدشده توسط pytest از آرشیو بازیابی و با `cmp` بایت‌به‌بایت تأیید شد و `tts_cache` (اثر جانبی تست) حذف شد؛ `next-env.d.ts` و هر فایل دیگر خارج از ۱۵تایی بایت‌به‌بایت یکسان‌اند.

## ۸. یادداشت‌های باقی‌مانده (غیر-مسدودکننده)

1. دو تغییر ریز رفتاری مستند فاز ۰۰-A پابرجاست: بدون دزدیدن فوکوس در مودال، و شروع بارگذاری‌ها یک microtask بعد از paint (از نظر بصری یکسان).
2. تست smoke همچنان opt-in (`PHASE4_PG_URL`)؛ پیشنهاد اتصال به CI با PG موقت در فازهای بعد.
3. در ChatRecycleBin لغو fetch هنگام تعویض تب انجام نمی‌شود — رفتار از قبل موجود و بی‌اثر بر درستی (بند ۲).
4. اسکریپت‌های بازبینی برای استفادهٔ مجدد ذخیره شدند: `scripts/review_migration_e1f2a3b4c5d6.py`، `scripts/review_mig_seed.py` (+ `pg_migration_check.py`، `run_pg_smoke.py` از فاز ۰۰-A).

## ۹. نتیجهٔ صریح

معیارِ «تأیید کامل کیفیت تغییرات، ایمنی migration و حفظ رفتارهای قبلی» برآورده شد: diff ۱۵ فایل سطربه‌سطر بازبینی و در سناریوهای race/stale/cleanup/props/تعویض‌سریع سالم؛ الگوی lint-فیکس شفاف تحلیل شد و راه‌های اصولی‌تر برای فازهای بعد ثبت شد؛ migration با ۱۶ سنجهٔ واقعی (شامل بررسی داده پیش از narrowing و کاوش منفی) ALL_OK؛ assertionهای تست دست‌نخورده؛ هر چهار gate رگرسیون سبز؛ و درخت کار دقیقاً محدود به changeset است.

**`PASS — READY FOR PHASE 01`**
