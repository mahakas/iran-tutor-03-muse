# بازبینی Phase 02-B — Idempotency دست‌به‌دست‌کردن (Handoff) دفترچه

> تاریخ: ۲۰۲۶-۱۱-۲۳ · هدف: جلوگیری قطعی از ثبت تکراری پاسخ معلم در دفترچه
> ## نتیجه: `PASS — NOTEBOOK HANDOFF IDEMPOTENT`

## ۱) بررسی رفتار قبلی (یافتهٔ واقعی)
درست است — در گزارش Phase 02-A دو POST موازی هر دو ثبت می‌شدند. ریشه: `add_block` هیچ هویتی برای «همین پیام» نداشت و دو درخواست موازی/دوباره‌ارسال هر بار بلوک مستقل می‌ساختند. busy-guard فرانت فقط کلیک دومِ همان رندر را می‌گرفت؛ POST موازی (دو تب، retry پس از timeout) از آن عبور می‌کرد.

## ۲–۴) شناسهٔ پایدار منبع و بازپخش تکراری
- هر ذخیرهٔ handoff اکنون `conversation_id` + `message_id` را در `metadata_json` بلوک حمل می‌کند (فرانت: `buildNotebookBlockFromMessage(message, title, {conversationId, messageId})`).
- کلیدهای `conversation_id`/`message_id` به `ALLOWED_METADATA_KEYS` سرویس اضافه شدند؛ max-length موجود (۳۰۰) حفظ شد.
- **درخواست تکراری برای همان (conversation_id, message_id) بلوک جدید نمی‌سازد**: پاسخ همان بلوکِ موجود با نشانهٔ `"idempotent_replay": true` است (API status همان 201 می‌ماند؛ هیچ قرارداد فعلی نشکست).

## ۵) Retry پس از timeout
retry با همان هویت → replay بلوک موجود، بدون ردیف جدید (تست‌شده واحد و زنده).

## ۶) busy-guard فرانت‌اند
حفظ شد و تقویت شد: دکمه با `disabled={notebookBusyId !== null}` قفل می‌ماند و خود callback اکنون هم اگر busy باشد زودتر return می‌کند (دفاع در عمق). متن موفقیت برای replay: «این پاسخ از قبل در دفترچهٔ این کتاب بود.»

## ۷–۸) کنترل هم‌زمانی بک‌اند بدون Migration غیرضروری
- بررسی وابستگی‌ها: `notebook_blocks.metadata_json` از قبل JSON است → **هیچ Migration جدیدی لازم نبود و ساخته نشد**.
- `add_block`: پس از بررسی مالکیت، ردیف notebook با `SELECT … FOR UPDATE` قفل می‌شود (سریال‌سازی insertهای موازیِ همان دفترچه؛ قابل‌حمل روی SQLite تست‌ها) و سپس چک تکراری انجام می‌شود — پنجرهٔ مسابقه بسته است.
- ساخت دفترچه: پارامتر اختیاری `dedupe_by_book` (query param `?dedupe_book=1` فقط از مسیر handoff فرستاده می‌شود) → قفل ردیف کاربر + بازاستفاده از دفترچهٔ موجود همان کتاب. مسیر عمومی ایجاد دفترچه (بدون فلگ) رفتار قبلی خود را کامل حفظ کرد (تست شد).

## ۹) ایمنی در برابر درخواست‌های هم‌زمان
مسابقهٔ سه‌گانهٔ موازیِ `?dedupe_book=1` روی استیجینگ: هر سه پاسخ → **یک** notebook. دو POST موازی بلوک با همان هویت → **یک** بلوک.

## ۱۰–۱۱) حفظ منبع و citation اصلی
- metadata حفظ می‌شود: `title` (عنوان کتاب)، `citation` (کتاب — فصل — صفحهٔ چاپی) و اکنون `conversation_id`/`message_id`.
- پاسخ بدون source: citation = فقط عنوان کتاب؛ هیچ فصل/صفحه‌ای جعل نمی‌شود (تست فرانت و زنده).
- چند source: فقط منبع اولِ واقعی citation می‌شود؛ دادهٔ منبع دوم وارد متن استناد نمی‌شود.

## تست‌های اجباری — نتیجه
| سناریو | سطح | نتیجه |
|---|---|---|
| دو کلیک سریع | واحد (بک) + زنده | **PASS** — یک بلوک |
| دو POST موازی | واحد (بک) + زنده (asyncio.gather) | **PASS** — یک بلوک |
| retry پس از timeout | واحد (بک) + زنده | **PASS** — replay |
| دو درخواست با message_id یکسان | واحد + زنده (۱+۴) | **PASS** |
| دو پیام متفاوت از یک گفت‌وگو | واحد + زنده | **PASS** — دو بلوک |
| دو کاربر مستقل | واحد + زنده (۶a/6b/6c) | **PASS** — 404 روی دفترچهٔ دیگری + دفترچهٔ خودش |
| پاسخ بدون citation | واحد فرانت + زنده | **PASS** — فقط عنوان کتاب |
| پاسخ با چند citation | واحد فرانت + زنده | **PASS** — citation اصلیِ واقعی |
| مسابقهٔ ساخت دفترچه (۳ موازی) | زنده | **PASS** — یک notebook |
| create عمومی بدون فلگ | واحد + زنده | **PASS** — رفتار قبلی حفظ شد |

زنده = سرور استیجینگ واقعی (backend :8001، PG staging) — اسکریپت: `scripts/staging_handoff_idempotency.py` → **۱۳/۱۳ PASS**.

## رگرسیون (هیچ تست قدیمی حذف/تضعیف نشد)
| دروازه | نتیجه |
|---|---|
| Backend pytest | **۵۰۴ passed / ۱ skipped** (قبلاً ۴۹۷ — +۷ تست جدید) |
| Vitest | **۹۹/۹۹** در ۱۳ فایل (قبلاً ۹۵ — +۴ تست جدید به فایل موجود handoffs اضافه شد، نه جایگزین) |
| TypeScript | exit 0 |
| ESLint | exit 0 |
| Production Build | exit 0 |
| تست‌های قبلی phase6 | همان فایل، بدون تغییر assertionها — همه سبز |

## فایل‌های تغییرکرده
- `backend/app/services/notebook_service.py` — هویت handoff، dedupe بلوک با قلب ردیفی، `dedupe_by_book`
- `backend/app/api/phase6.py` — query param `dedupe_book` روی POST /notebooks
- `frontend/lib/handoffs.ts` — `buildNotebookBlockFromMessage` با handoffRef اختیاری
- `frontend/components/StudentApp.tsx` — ارسال ids، `?dedupe_book=1`، پیام replay، دفاع busy
- `backend/tests/test_phase6_rich_study.py` — +۷ تست idempotency (اضافه)
- `frontend/tests/handoffs.test.ts` — +۴ تست (اضافه به فایل موجود)

## محدودیت‌ها
- قفل `FOR UPDATE` روی PostgreSQL معنی واقعی دارد؛ در SQLite (تست‌ها) no-op است و سریال‌سازی از ماهیت تک‌نویسندهٔ SQLite می‌آید — روی استیجینگ PG مسابقهٔ واقعی هم‌زمانی تست شد و سبز است.
- replay پاسخ 201 با نشانهٔ `idempotent_replay` برمی‌گرداند (نه 200) تا قرارداد فعلی کلاینت‌های موجود نشکند.

## Rollback
`git checkout -- backend/app/services/notebook_service.py backend/app/api/phase6.py frontend/lib/handoffs.ts frontend/components/StudentApp.tsx backend/tests/test_phase6_rich_study.py frontend/tests/handoffs.test.ts` (بدون تغییر اسکیمای DB — بازگشت فوری).
