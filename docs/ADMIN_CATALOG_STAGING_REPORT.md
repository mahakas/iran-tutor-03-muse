# گزارش استقرار Staging — مدیریت کاتالوگ ادمین (Staging Deployment Checklist)

> تاریخ: ۲۰۲۶-۱۱-۲۳ · هدف: اعتبارسنجی استقرار Staging طبق چک‌لیست ۱۵ بندی
> ## نتیجه: `PASS — STAGING VERIFIED`

## ۱–۲) وضعیت Git و checkout
- شاخهٔ `main`، worktree **تمیز** (۰ تغییر تأییدنشده / ۰ untracked). commitها اسنپ‌شات خودکار محیط‌اند؛ توسط این گزارش هیچ commit/push/merge انجام نشده.
- همهٔ فایل‌های کاتالوگ/RBAC در checkout واقعی حاضرند: `app/api/admin_catalog.py`، `app/services/permissions.py` (شامل `can_manage_education_catalog`)، دو migration (`b8c9d0e1f2a3`، `c9d0e1f2a3b4`)، تست RBAC، سه سند.

## ۳) پشتیبان‌گیری
- `pg_dump` از دیتابیس staging **قبل از migration**: `scripts/staging_backup_pre_migrations.sql` (۱۳۰,۰۱۲ بایت).
- **درام بازیابی:** بازگردانی موفق به `darsyar_staging_restore` — head بازیابی‌شده = `e1f2a3b4c5d6` (وضعیت pre-catalog)، جدول `grades` با ۰ ردیف = همان لحظهٔ بکاپ.

## ۴–۵) PostgreSQL و Alembic head
- **PostgreSQL 16.2** (x86_64-pc-linux-gnu).
- head قبل از استقرار: `e1f2a3b4c5d6` (وضعیت واقع‌نما قبل از استقرار) → **بعد از استقرار: `c9d0e1f2a3b4 (head)`** — تک head، مطابق انتظار. هیچ اختلافی دیده نشد.

## ۶) Migrationها — فقط روی Staging
- `alembic upgrade head` فقط روی `darsyar_staging` (instance PostgreSQL دورریختنیِ محلی). هیچ دیتابیس Production/توسعه‌ای لمس نشده است.

## ۷) Seedها — بدون دادهٔ تکراری
- **یافته و رفع باگ واقعی:** اجرای دومِ seed یک ردیف تکراری در `catalog_import_runs` می‌ساخت (۱→۲). رفع شد: رانِ بدون تغییر اکنون ردیف run خود را حذف می‌کند (`app/db/catalog_seed.py` — تشخیص no-op با شمارش ردیف‌های قبل/بعد).
- اثبات idempotency: شمارش‌ها پس از seed دوم یکسان ماند — cycles 3، branches 3، grounds 8، programs 118، textbooks 211، course-textbooks 303، sources 1، import-runs **۱→۱**، grades 12، majors 3.

## ۸) ۱۴ صفحهٔ مدیریت کاتالوگ با نقش admin (مرورگر واقعی)
هر ۱۴ صفحه با ورود واقعی admin از UI (فرم ورود پنل) بازدید و رندر شد — صفر خطای صفحه:
cycles · grades · branches · grounds · programs · subjects · textbooks · editions · links · years · audiences · special · validity · archive

## ۹–۱۰) عملیات و RBAC (۲۷/۲۷ PASS زنده)
- CRUD: ایجاد/ویرایش cycle، ایجاد/حذف امن ground ✓ · آرشیو/بازیابی کتاب ✓ · PDF نامعتبر → 422، معتبر → ذخیره ✓
- **PDF هرگز ready خودکار نمی‌شود** (ready=None پس از آپلود؛ انتشار فقط از مسیر ingest) ✓
- Audit Log: endpoint درست `/api/v1/admin/action-logs`؛ رکوردهای `catalog.textbooks.archive`، `catalog.editions.pdf-upload` و… ثبت شده‌اند ✓
- RBAC چهار نقش: moderator/teacher/student → **403** روی خواندن و نوشتن؛ ناشناس → **401**؛ در UI هم gate قفل برای نشست بدون ادمین ✓ (پروب‌ها با client بدون cookie — cookie ادمین نباید نشت کند)

## ۱۱–۱۲) انتخاب‌گر دانش‌آموز و Self-Service
- تغییر عنوان درس توسط ادمین → بلافاصله در `/api/v1/curriculum/subjects` عمومی دیده شد ✓ (و برگردانده شد)
- پروفایل تحصیلی: دانش‌آموز خودش پایه/شاخه/رشته را با `PUT /api/v1/account/academic-profile` ثبت کرد؛ دانش‌آموز دیگر خالی ماند؛ عملیات کاتالوگ (آرشیو/بازیابی) پروفایل را دست‌نخورده گذاشت؛ **ادمین → 401 روی نوشتن پروفایل** ✓

## ۱۳) PDF فاقد پردازش معتبر
- فایل غیر PDF → 422؛ فایل `%PDF-` → فقط ذخیره+checksum؛ هیچ مسیری ready نمی‌سازد ✓

## ۱۴–۱۵) رگرسیون، Smoke و خطاها
| دروازه | نتیجه |
|---|---|
| Backend pytest | **۴۹۷ passed / ۱ skipped** (exit 0) |
| Vitest | **۱۳ فایل / ۹۵ تست** ✓ |
| TypeScript | exit 0 |
| ESLint | exit 0 |
| Production Build | exit 0 |
| Smoke سرور استیجینگ | `/health` 200؛ فرانت 200 |
| اسکن لاگ بک‌اند | بدون 5xx غیرمنتظره (فقط 401/403/422 عمدیِ تست RBAC) |

## محدودیت‌ها و نکات استقرار
- «Staging» = PostgreSQL محلیِ دورریختنی با جریان واقعی بکاپ→migration→seed؛ محیط استیجینگ اشتراکی در دسترس نبود.
- **نکتهٔ استقرار مهم:** مقصد `rewrites()` فرانت در زمان `next build` پخته می‌شود — `BACKEND_ORIGIN` باید **هنگام build** تنظیم شود (در این اجرا اعمال شد).
- در حالت `next dev` صفحهٔ /admin در مرورگر headless روی اسپینر می‌ماند (hydration dev-mode)؛ در build تولیدی همان جریان درست کار می‌کند — بررسی UI روی build انجام شد.
- ورود آزمون/چت به یک LLM جعلی سازگار با OpenAI (`scripts/fake_llm_server.py`) وصل شد تا مسیرهای AI-دار روی استیجینگ قابل آزمون باشند.

## Rollback
- `alembic downgrade b8c9d0e1f2a3` (فقط ستون‌های مدیریتی) یا `alembic downgrade e1f2a3b4c5d6` (حذف کامل کاتالوگ) — هر دو قبلاً روی PG دورریختنی اعتبارسنجی شده‌اند؛ در درام این گزارش بازیابی از بکاپ هم موفق بود.
