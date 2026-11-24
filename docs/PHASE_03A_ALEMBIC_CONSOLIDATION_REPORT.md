# گزارش Phase 03-A — یکپارچه‌سازی زنجیرهٔ Alembic

> تاریخ: ۲۰۲۶-۱۱-۲۴ · شاخهٔ پیشنهادی: بدون شاخهٔ جدید (تغییری در کد/migration ایجاد نشد)
> ## نتیجه: `PASS — ALEMBIC SINGLE HEAD RESTORED`

## ۱) خلاصهٔ یافتهٔ اصلی — اصلاح مقدمهٔ فاز

ادعای گزارش Phase 03 مبنی بر «سه head موازی و ابهام `upgrade head`» **نادرست بود و در همین فاز با ابزار مرجع (خود Alembic) رد شد.** علت: در فاز 03 یک اسکریپت grep/awk سرصفحه‌ای برای استخراج down_revisionها استفاده شده بود که (الف) `down_revision` توییپ‌مانند را فقط با اولین والد ثبت می‌کرد و (ب) نام فایل را با `revision` داخل فایل اشتباه می‌گرفت. بررسی مرجع:

```
$ alembic heads --verbose          (Alembic 1.20.1)
Rev: a1b2c3d4e5f9 (head)           ← فقط یک head
Parent: c9d0e1f2a3b4
Path: backend/alembic/versions/a1b2c3d4e5f9_phase3_flashcard_reports.py
```

`ScriptDirectory.get_heads()` نیز دقیقاً `['a1b2c3d4e5f9']` برمی‌گرداند. توپولوژی واقعی: دو شاخهٔ تاریخی (`d4e5f6a7b8c9` خط Phase-7-drift و `f6a7b8c9d0e1` خط Iran-Curriculum-Core) **از قبل** با یک merge revision استاندارد یکپارچه شده‌اند:

- فایل: `alembic/versions/a1b2c3d4e5f6_curriculum_unit_branch_scope.py`
- داخل فایل: `revision = "d1e2f3a4b5c6"` · `down_revision = ("d4e5f6a7b8c9", "f6a7b8c9d0e1")`

`c9d0e1f2a3b4` هرگز head سوم نبوده؛ فرزند همان خط اصلی است و migration فلش‌کارت فاز 03 (`a1b2c3d4e5f9`) روی آن سوار است و اکنون **head یکتای زنجیره** است.

## ۲) تصمیم فنی: merge revision جدید ساخته نشد (عمداً)

ساختن merge revision روی زنجیرهٔ تک‌head فنی بی‌معناست (Alembic فقط با چند head اجازهٔ merge می‌دهد و merge تک‌والد صرفاً یک revision خالی گمراه‌کننده اضافه می‌کند). بنابراین به‌جای افزودن artifact زائد، صحت زنجیره با شواهد زیر اثبات شد. خطوط قرمز: هیچ migration حذف/بازنویسی نشد (`git diff HEAD -- backend/alembic/` = 0 خط)، migration فلش‌کارت در زنجیرهٔ نهایی حفظ شد، هیچ commit/push/merge انجام نشد.

## ۳) بررسی همهٔ revisionها و علّت شاخه‌های تاریخی

۲۷ فایل migration. علت ایجاد دو شاخهٔ تاریخی: توسعهٔ موازی دو قابلیت (سازگاری schema در Phase-7 و هستهٔ آموزشی ایران) از دو والد مشترک؛ این وضعیت در گذشته با merge استاندارد `d1e2f3a4b5c6` بسته شده است. هیچ شاخهٔ بازی باقی نمانده.

## ۴) اثبات‌های اجراشده روی PostgreSQL مستقل (PG 16.2، Alembic 1.20.1)

اسکریپت: `scripts/phase03a_migration_proofs.py` روی DB خالی `phase03a_single_head`:

| آزمون | نتیجه |
|---|---|
| `alembic upgrade head` از DB کاملاً خالی | موفق — ۲۷ revision، ۶۳ جدول، head یکتا `a1b2c3d4e5f9` |
| `alembic check` روی همان DB | `No new upgrade operations detected.` |
| درج دادهٔ آزمایشی FK-معتبر (user→grade→book→page→deck→card→review→report) + join یکپارچگی | 1 ردیف پیوسته، OK |
| `downgrade -1` (→ `c9d0e1f2a3b4`) و `upgrade head` | جدول `flashcard_reports` طبق طراحی drop/re-create می‌شود؛ users/books/pages/decks/cards/reviews **دست‌نخورده ماندند** |
| پایین‌رفتن تا نقطهٔ merge و هر دو tip شاخه: `d1e2f3a4b5c6` → `f6a7b8c9d0e1` → بازگشت → `d4e5f6a7b8c9` → بازگشت | هر چهار یالِ اطراف merge سالم و رفت‌وبرگشت‌پذیر |
| `downgrade base` کامل → `upgrade head` | **نقص از قبلِ مخزن کشف شد** (بند ۵)؛ پس از پاک‌سازی دستی enumها بازگشت کامل تا head و `check` پاک ✓ |

## ۵) یافتهٔ جدید: نشتی enum type در downgrade کامل به base (از قبلِ مخزن)

`downgrade base`، جدول‌ها را حذف می‌کند اما enum typeهای `book_status` و `page_status` (ساخته‌شده در migration اولیهٔ `a04a943af8b1_initial` از طریق `sa.Enum`) را `DROP TYPE` نمی‌کند؛ اجرای مجدد `upgrade head` با خطای `type "book_status" already exists` متوقف می‌شود. **اصلاح آن مستلزم بازنویسی migration اولیه است که خط قرمز همین فاز است**؛ بنابراین مستند شد: مسیر پشتیبانی‌شدهٔ rollback مانند RELEASE_READINESS، downgrade «نقطه‌ای» است (اثبات‌شده و پاک) و downgrade کامل به base نیازمند گام دستی DBA است:

```sql
DROP TYPE IF EXISTS book_status; DROP TYPE IF EXISTS page_status;
```

پس از همین گام، بازگشت کامل تا head و `check` پاک اثبات شد (۶۳ جدول).

## ۶) وضعیت Staging (بدون اتصال به Production)

- `alembic_version` قبل: `a1b2c3d4e5f9` → `alembic upgrade head` بدون ابهام و بدون عملیات (از قبل head) → بعد: `a1b2c3d4e5f9`.
- `alembic check` روی staging: `No new upgrade operations detected.` (برخلاف یادداشت قدیمی RELEASE_READINESS دربارهٔ drift فقط-SQLite، staging PG هم کاملاً همگام است).
- سازگاری کد/DB با اسموک زندهٔ فلش‌کارت (`scripts/staging_flashcards_phase03.py`): **10/10 PASS** — شامل last_review واقعی، گزارش ایراد 201/409/422، ویرایش PATCH، مرور SM-2، session، export و ownership.

## ۷) ریسک‌ها و تصمیم‌های مالک

1. نشتی enum در downgrade کامل به base (بند ۵) — تصمیم مالک: پذیرش گام دستی DBA یا مجوز آینده برای یک migration جبرانی/بازنویسی محافظت‌شدهٔ initial.
2. گزارش Phase 03 (بند ریسک «سه head») با همین گزارش اصلاح می‌شود؛ متن فعلی آن گزارش به‌عنوان سابقه باقی می‌ماند.
3. نام فایل vs شناسهٔ revision در merge موجود (`a1b2c3d4e5f6_...` با `revision = d1e2f3a4b5c6`) ناهماهنگ است؛ بی‌ضرر ولی برای خوانایی آینده قابل تعمیر است.

## Rollback

هیچ تغییر دائمی اعمال نشده است: کد/migration دست‌نخورده (0 خط diff)، DB استیجینگ فقط تا head ایستاده بود که از قبل روی آن بود. DB آزمون `phase03a_single_head` ساختگی است و حذف آن اثر خارجی ندارد (`DROP DATABASE phase03a_single_head`).

## چک‌لیست دستی بازبینی (فارسی)

1. `alembic heads` → فقط `a1b2c3d4e5f9 (head)` — بدون «Multiple heads».
2. `alembic upgrade head` روی هر DB استیجینگ → بدون خطا/بدون عملیات.
3. `alembic check` → `No new upgrade operations detected.`
4. `alembic history` → مسیر merge `d1e2f3a4b5c6` دیده می‌شود و `a1b2c3d4e5f9` (فلش‌کارت) انتهای زنجیره است.
5. اپ استیجینگ `/flashcards` → ساخت/مطالعه/گزارش/خروجی طبق اسموک ۱۰/۱۰.

## نتیجه

`PASS — ALEMBIC SINGLE HEAD RESTORED`
(zنجیره تک‌head، upgrade موفق از DB خالی، check موفق روی DB خالی و staging، سازگاری PostgreSQL 16.2، حفظ تمام ۲۷ migration قبلی + migration فلش‌کارت فاز 03)
