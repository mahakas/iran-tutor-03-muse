# گزارش Phase 03 — بازطراحی کامل تجربهٔ فلش‌کارت

> تاریخ: ۲۰۲۶-۱۱-۲۳ · شاخهٔ پیشنهادی برای بازبینی مالک: `redesign/phase-03-flashcards`
> ## نتیجه: `PASS`

## ۱) خلاصهٔ تغییرات و دلیل

موتور مرور SM-2 و همهٔ قراردادهای API دست‌نخورده ماندند. بازطراحی روی gapهای اثبات‌شدهٔ UX نسبت به الزامات فاز انجام شد:

| الزام فاز | وضعیت قبل | تغییر |
|---|---|---|
| جست‌وجو و فیلتر کتابخانه | نبود | جست‌وجوی عنوان + فیلتر وضعیت مطالعه (همه / برای مرور / تازه / دارای تسلط) روی دادهٔ واقعی API؛ حالت «بدون نتیجه» |
| وضعیت مطالعه و آخرین مرور | فقط progress | `last_review` واقعی (max `reviewed_at` ردیف‌های SM-2) به `serialize_deck`/`deck_stats` اضافه و در کارت دسته‌ها و نمای دسته نمایش داده می‌شود |
| پیش‌نمایش قبل از تولید | نبود | جعبهٔ «پیش‌نمایش درخواست» در مودال ساخت: کتاب انتخابی، محدودهٔ فصل/صفحه، تعداد، سطح، مقصد + یادآوری اعتبارسنجی سمت سرور (هیچ دادهٔ جعلی نشان داده نمی‌شود) |
| ویرایش کارت | API موجود (`PATCH /cards/{id}`) ولی بدون UI | دیالوگ «جزئیات کارت»: ویرایش front/back/hint با busy-guard و پیام خطا و حفظ مقادیر هنگام شکست |
| گزارش ایراد | نبود (gap اثبات‌شده در خود فاز) | مدل `FlashcardReport` + migration + `POST /cards/{id}/report` (دلیل از واژگان مشترک feedback، یک گزارش باز برای هر کارت/کاربر → 409) + صف triage ادمین (`GET/PATCH /api/v1/admin/flashcards/reports`) + UI گزارش در دیالوگ |
| حذف کارت | موجود | حفظ شد؛ در دیالوگ هم در دسترس است |
| بازیابی کارت | نبود | **انجام نشد (تصمیم مستند):** نیاز به ستون soft-delete + نگهداری تاریخچهٔ SM-2 پس از حذف دارد؛ طبق ممنوعیت تغییر review history بدون migration اختصاصی و تست، به تصمیم مالک موکول شد |
| مطالعه/۴ دکمهٔ SM-2 | موجود | حفظ کامل: صفحهٔ Legacy چهاردرجه‌ای (فراموش کردم/سخت/خوب/آسان) و مسیر session با got/missed که سرور به rating 3/1 نگاشت می‌کند — بدون تغییر |
| پایان session | موجود (ResultsScreen) | حفظ شد |
| خروجی Anki/CSV | موجود | حفظ و تست شد (زنده: 200/200) |
| منبع دقیق/صفحهٔ چاپی | citations در کارت | در دیالوگ جزئیات + صفحهٔ چاپی جدا نمایش داده می‌شود؛ خط provenance دفترچه (فصل/صفحه) به نمای دسته اضافه شد |

## ۲) فایل‌های تغییرکرده/جدید

- `backend/app/models/flashcards.py` — مدل `FlashcardReport` + ثابت‌های `REPORT_REASONS`/`REPORT_STATUSES`
- `backend/alembic/versions/a1b2c3d4e5f9_phase3_flashcard_reports.py` — migration جدید (زنجیر از `c9d0e1f2a3b4` = head واقعی staging)، reversible
- `backend/app/services/flashcard_service.py` — `last_review` در `deck_stats`/`serialize_deck`؛ `report_card`/`resolve_report`/`admin_list_reports`/`serialize_report`
- `backend/app/api/flashcards.py` — `POST /api/v1/flashcards/cards/{id}/report`، `GET/PATCH /api/v1/admin/flashcards/reports[/{id}]` (درون `admin_router` با `require_admin`)
- `frontend/lib/flashcards.ts` — `stats.last_review` + `CARD_REPORT_REASONS`
- `frontend/components/FlashcardsWorkspace.tsx` — کنترل‌های کتابخانه، دیالوگ جزئیات کارت (`CardDetailsDialog`)، پیش‌نمایش ساخت، خط provenance، دکمهٔ جزئیات ردیف کارت
- `frontend/app/globals.css` — کلاس‌های جدید UI
- `frontend/tests/FlashcardsWorkspace.test.tsx` — +۷ تست جدید (تست‌های قبلی حفظ شدند)
- `backend/tests/test_phase3_flashcards.py` — +۳ تست جدید (تست‌های قبلی حفظ شدند)

## ۳) قابلیت‌های حفظ‌شده و تست محافظ

- الگوریتم SM-2، due، ease factor، review history: **بدون تغییر** — محافظ: `tests/test_phase3_flashcards.py` (41 تست قبلی شامل رفتار rating/interval) و `tests/test_phase8_flashcard_study.py` — همه سبز.
- ownership و capability-gating: محافظ با تست‌های قبلی + تست جدید «گزارش کارت دیگران → 404».
- export Anki/CSV: تست زندهٔ اسموک (200/200).
- تولید از کتاب/گفت‌وگو/اشتباهات با citation: تست‌های قبلی حفظ.
- هیچ assertion قدیمی حذف یا تضعیف نشد؛ فقط fixture نوعی تست فرانت با فیلد اجباری جدید (`last_review: null`) کامل شد.

## ۴) فرمان‌های اجراشده و خروجی واقعی

| فرمان | خروجی |
|---|---|
| `pytest -q tests/test_phase3_flashcards.py tests/test_phase8_flashcard_study.py` | `41 passed` |
| `pytest -q tests` (کل) | `507 passed, 1 skipped, 2 warnings in 238s` · EXIT=0 |
| `vitest run` (دو بار پیاپی) | `13 files / 107 passed` در هر دو اجرا |
| `tsc --noEmit` | exit 0 |
| `npm run lint` | exit 0 |
| `next build` (BACKEND_ORIGIN=:8001) | BUILD_EXIT=0 |
| `alembic upgrade a1b2c3d4e5f9` → `downgrade c9d0e1f2a3b4` → `upgrade` روی PG استیجینگ | ارتقا → جدول ساخته شد (7 ستون) → برگشت → جدول حذف شد → ارتقای مجدد ✓ |
| اسموک زندهٔ استیجینگ (`scripts/staging_flashcards_phase03.py`) | **10/10 PASS** — last_review واقعی، گزارش 201/409/422، ویرایش PATCH، مرور SM-2، session missed، export، ownership |

## ۵) تست‌های اجرا‌نشده و دلیل

- هیچ سوییتی اجرا نشده باقی نماند. تنها محدودیت: تست‌های UI از مسیر `vitest/jsdom` مدل واقعی LLM را شبیه‌سازی می‌کنند (مطابق قواعد فاز)؛ کیفیت تولید واقعی کارت‌ها با مدل زنده در این فاز ادعا نشده و خارج از دامنهٔ تست است.

## ۶) ریسک‌های باقیمانده و تصمیم‌های مالک

1. **بازیابی کارت حذف‌شده:** نیازمند soft-delete + migration اختصاصی و سیاست نگهداری review history — نیازمند تصمیم مالک.
2. **سه head موازی در زنجیرهٔ Alembic** (وضعیت از قبلِ مخزن): `upgrade head` تکی خطا می‌دهد؛ staging روی `c9d0e1f2a3b4` بود و migration جدید از همان زنجیر شد. توصیه: مالک با یک merge revision زنجیره را یکپارچه کند.
3. **حلقهٔ re-render مودال ساخت** (effect امتحان‌ها با وابستگی `authFetch` در هر re-render والد دوباره اجرا می‌شود — تا ~۵۰ بار در تست‌ها): رفتار از قبل موجود، بی‌ضرر ولی ناکارا؛ اصلاحش (StableCallback) خارج از دامنهٔ این فاز بود.
4. **flake تست فرانت ریشه‌یابی و رفع شد:** ترکیب `restoreMocks:true` کانفیگ + `restoreAllMocks` دستیِ afterEach، mock را در بازهٔ flush معلق یک درخت React تستِ قبلی خالی می‌کرد؛ restore دستی حذف شد (پوشش توسط کانفیگ) و دو اجرای کامل متوالی سبز شد.
5. triage ادمین فعلاً API-only است (صف در `/api/v1/admin/flashcards/reports`)؛ UI ادمین نیازمند تصمیم مالک.

## Rollback

`git checkout -- backend/app/models/flashcards.py backend/app/services/flashcard_service.py backend/app/api/flashcards.py backend/tests/test_phase3_flashcards.py frontend/lib/flashcards.ts frontend/components/FlashcardsWorkspace.tsx frontend/app/globals.css frontend/tests/FlashcardsWorkspace.test.tsx && rm backend/alembic/versions/a1b2c3d4e5f9_phase3_flashcard_reports.py` و در صورت اعمال روی DB: `alembic downgrade c9d0e1f2a3b4`.

## ۷) چک‌لیست تست دستی فارسی (مسیرهای UI/API)

1. `/flashcards` → کتابخانه: جست‌وجوی «حروف» ، فیلتر «برای مرور امروز» / «تازه» / «تسلط‌یافته»؛ نمایش «آخرین مرور: …».
2. «ساخت با هوش مصنوعی» → تب کتاب: پایه/رشته/کتاب/فصل → مشاهدهٔ «پیش‌نمایش درخواست» → ساخت → پردازش → خطا (قطع شبکه) → retry با حفظ فرم.
3. ورود به دسته → دکمهٔ «جزئیات کارت» (آیکن چشم) → منبع/صفحهٔ چاپی → «ویرایش» → ذخیره → «گزارش ایراد» → ثبت → پیام موفقیت → دکمهٔ گزارش محو می‌شود.
4. مطالعهٔ کامل/مرور هوشمند → reveal → بلد بودم/بلد نبودم → صفحهٔ نتایج → مرور فقط بلد نبودم‌ها.
5. مرور امروز (چهار دکمهٔ SM-2) → ثبت rating → بازگشت.
6. دانلود CSV و خروجی Anki.
7. کاربر دوم: `/flashcards` → دستهٔ کاربر اول دیده نمی‌شود؛ report روی کارت او → 404.

## ۸) نتیجه

`PASS` — همهٔ معیارهای فاز ۰۳ اثبات شدند: مسیر کامل ساخت → مطالعه → ثبت مرور → نتیجه کار می‌کند؛ تست‌های SM-2/ownership/UI سبز؛ همهٔ کارت‌های کتاب‌محور citations/provenance قابل مشاهده دارند؛ خروجی‌ها و busy-guard/double-submit حفظ شده‌اند.
