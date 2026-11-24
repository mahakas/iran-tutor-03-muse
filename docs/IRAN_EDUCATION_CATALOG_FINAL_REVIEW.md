# کنترل کیفیت نهایی کاتالوگ آموزشی ۱۴۰۵–۱۴۰۶ — گزارش بازبینی

> **تاریخ:** ۲۰۲۶-۱۱-۲۳ · **محدوده:** بازبینی نهایی + ADDENDUM (مدیریت کامل کاتالوگ توسط ادمین)
> ## نتیجه: `PASS — CATALOG READY FOR STAGING`

---

## ۱) مالکیت پروفایل تحصیلی (سیاست قطعی مالک)

**بسته‌شده:** سه endpoint مدیریتی که امکان تغییر `grade_level`/`major` می‌دادند:
- `POST /api/v1/admin/users` (ایجاد کاربر) — فیلدهای تحصیلی حذف و `extra="forbid"` شد → ارسالشان 422 می‌دهد.
- `PATCH /api/v1/admin/users/{id}` — `grade_level/major/clear_grade` حذف شدند → 422.
- `PUT /api/v1/admin/users/{id}/role` — `grade_level/major` حذف شدند → 422.

سایر قابلیت‌های مدیریت کاربران (نام، ایمیل، شماره، نقش، فعال‌سازی، سهمیه) دست‌نخورده ماند. فرم‌های فرانت ادمین (کاربران + نقش‌ها) فیلدهای تحصیلی‌شان حذف/فقط‌مشاهده شد.

**تست:** `tests/test_admin_academic_profile_isolation.py` — ۴ تست: رد loudly با 422، دست‌نخوردگی placement پس از تلاش مدیر، ادامهٔ self-service دانش‌آموز، نمایش read-only در پروندهٔ ادمین. نتیجه: ۴/۴ ✓

## ۲) وضعیت اعتبار رشته‌های هنرستانی

۱۱۸ رشته همه `needs_verification` ماندند (هیچ رشته‌ای بدون مدرک `active` نشده). **انتخاب دانش‌آموز از وضعیت رسمی جدا شد:** گزینه‌های انتخاب‌گر `validity_status` را حمل می‌کنند؛ UI برای رشته‌های نیازمند راستی‌آزمایی برچسب صادقانه می‌نویسد («وضعیت اعتبار رسمی این رشته: نیازمند راستی‌آزمایی — … هیچ تأیید مدیریتی لازم ندارد»)؛ هیچ‌گاه «فعال/تأییدشده» معرفی نمی‌شوند. پروفایل serialized هم `field_validity_status` دارد و **پنل مدیریت وضعیت اعتبار را در کارت «پروفایل تحصیلی (فقط مشاهده)» نمایش می‌دهد.** تست اختصاصی ✓

## ۳) کاتالوگ کتاب‌ها — شمارش واقعی از DB پس از Seed (`scripts/catalog_report_counts.py`)

| کمیت | تعداد |
|---|---|
| دارای عنوان | **۲۱۱** |
| دارای کد رسمی | **۰** (همه NULL — هیچ کد ساختگی تولید نشد) |
| دارای نسخهٔ سال ۱۴۰۵–۱۴۰۶ | **۲۱۱** (+ ۳۰۳ ارتباط آموزشی) |
| دارای PDF | **۰** (نسخه‌های واقعی فاقد PDF؛ هویت نسخه = جدول books مستقل از عنوان) |
| ready | **۰** (قانون انتشار خودکار: ready فقط توسط خط پردازش) |
| نیازمند بررسی | **۲۱۱** (validity ≠ active برای همه — صادقانه) |
| بدون پایهٔ قطعی | ۱ («از ایرانمان دفاع می‌کنیم») |

تخصصی فنی‌وحرفه‌ای و کاردانش همچنان خارج از دامنه؛ مشترک‌های فنی‌وحرفه‌ای حفظ شدند؛ هیچ داده‌ای حذف نشد.

## ۴) بازبینی Migration روی PostgreSQL مستقل (D-002)

**زیرساخت:** یک PostgreSQL دورریختنی با `pgserver` (data dir در /tmp — اتصال به هیچ دیتابیس واقعی). اسکریپت: `scripts/catalog_pg_migration_check.py` — هر ۸ مرحله اجرا و پاس:

1. مهاجرت تا head قبلی + درج رکورد کاربر واقعی ✓
2. upgrade تا head ✓
3. **`alembic check`: «No new upgrade operations detected»** ✓
4. Seed ساختار + کاتالوگ (grades=12, fields=122, books=211) ✓
5. اجرای دوباره Seed → صفر تکرار (created=0, books=211, links=303) ✓
6. سلامت FK (۲۵ کلید خارجی روی جداول کاتالوگ بررسی شد) ✓
7. downgrade یک‌ مرحله‌ای → رکورد کاربر سالم، ستون‌های مدیریتی حذف، جداول قبلی حفظ ✓
8. re-upgrade → کاربر سالم + کاتالوگ بازساخته (۲۱۱) ✓

**چهار مغایرت واقعی که `alembic check` گرفت و در migration اصلاح شد:**
- `catalog_import_runs.stats` باید JSONB باشد (مدل `JSON().with_variant(JSONB, "postgresql")`) — migration قبلاً `JSON` می‌ساخت؛ اصلاح شد.
- ایندکس گم‌شدهٔ `ix_program_availability_catalog_source_id` اضافه شد.
- `student_academic_profiles.user_id`: از UniqueConstraint نام‌دار به unique INDEX مطابق مدل تبدیل شد.
- downgrade متناظر هر سه اصلاح شد.

## ۵) نام فیلدهای مدل — `ground_id`

نام واقعی ستون در `app/models/curriculum.py` (خط ۷۸) **`ground_id`** است و در migration (۸ ارجاع)، سرویس/API پروفایل و seed همه همان نام استفاده می‌شود — **mismatch وجود ندارد؛ نام گزارش صحیح بود** و نیازی به migration اصلاحی نبود. (ستون دوم با همان نام در `student_academic_profiles` و `catalog_course_textbooks` عمداً بدون ground است؛ رشته، ground را حمل می‌کند.)

## ۶) Self-Service و RAG — دو حساب مستقل

تست `test_profile_change_keeps_history_and_rebinds_next_requests` + تست‌های ایزولاسیون: مالکیت پروفایل بین دو حساب نشت نمی‌کند؛ تغییر پایه ۵→۷ و ۱۲→۱۰ اعمال می‌شود؛ **تاریخچهٔ گفت‌وگو با پایهٔ خودِ جلسه حفظ می‌شود** (حذف/ترکیب نشد)؛ درخواست بعدی به سقف پایهٔ جدید بسته می‌شود (کتاب پایهٔ ۱۲ پس از کاهش به ۱۰ → 422). RAG per-request و stateless است — cache وابسته به پایه وجود ندارد.

## ۷) تست واقعی رابط کاربری (Playwright — Chromium واقعی)

اجرا روی استک زنده: backend واقعی (:8010) + Next production server (:3211) — **۹/۹ PASS** (`scripts/r7_ui_test.py`):
- ادمین: ایندکس بخش با ۱۴ ماژول ✓ · جدول پایه‌ها ✓ · فرم ایجاد (AJAX) ✓ · ماژول کتاب‌ها با دکمهٔ آرشیو ✓ · کارت «پروفایل تحصیلی (فقط مشاهده)» در پروندهٔ کاربر ✓ · بدون overflow افقی در ۳۷۵px ✓
- دانش‌آموز: gate «یک قدم اول» ✓ · انتخاب مرحله‌ای پایه→شاخه→رشته با ذخیرهٔ AJAX و persistence در صفحهٔ پروفایل ✓ · محو شدن gate پس از ذخیره و ماندگاری پس از reload ✓
- **تست تم تاریک جداگانه انجام نشد** (تم پیش‌فرض روشن در اجرا) — صادقانه در «انجام‌نشده» ثبت می‌شود، نه PASS.

**نکتهٔ محیطی:** در `next dev` این sandbox هیدراسیون React روی همهٔ مسیرهای ادمین (از قبل موجود هم) اجرا نمی‌شد (مشکل محیطی HMR/WebSocket)؛ اجرای واقعی روی `next start` (production build) انجام شد.

## ۸) رگرسیون کامل (نتایج واقعی)

| دروازه | نتیجه |
|---|---|
| Backend pytest (کل سوئیت) | **۴۹۶ passed / ۱ skipped** — شامل ۱۷ تست کاتالوگ + ۶ تست ایزولاسیون/تاریخچه + ۶ تست CRUD ادمین |
| Frontend Vitest | **۱۳ فایل / ۹۵ تست پاس** |
| TypeScript (`tsc --noEmit`) | exit 0 |
| ESLint | exit 0 |
| Production Build | ✓ Compiled successfully |
| PostgreSQL migration (۸ مرحله + alembic check) | ✓ همه پاس |

**تصحیح صادقانه نسبت به گزارش قبلی:** (۱) «lint exit 0» گزارش قبلی به‌خاطر pipeline اشتباه (`| tail`) بوده — lint اکنون واقعاً صفر است؛ (۲) «chain check روی SQLite» گزارش قبلی عملاً no-op روی DB ازقبل‌مهاجرت‌شده بوده — زنجیرهٔ کامل روی SQLite تازه از migration قدیمی `f3a4b5c6d7e8` (ALTER بدون batch mode، قبل از کارهای ما) شکست می‌خورد؛ مرجع رسمی migration طبق D-002 همان PostgreSQL است که کامل پاس شد.

**دو باگ مهم که در این بازبینی پیدا و رفع شد:**
1. **امنیتی:** router جدید `/api/v1/admin/catalog/*` بدون `Depends(require_admin)` بود — فراخوانی ناشناس actor پیش‌فرض «admin» می‌گرفت. با guard سطح router بسته شد؛ تست اختصاصی جلوگیری از دسترسی دانش‌آموز/ناشناس اضافه شد.
2. `alembic check` چهار drift واقعی schema را گرفت (بند ۴) — اصلاح شد.

## ۹) ADDENDUM — مدیریت کامل کاتالوگ توسط ادمین (خلاصه؛ سند کامل: `ADMIN_EDUCATION_CATALOG_MANAGEMENT.md`)

بخش مستقل «مدیریت نظام آموزشی و کاتالوگ درسی» در پنل مدیریت (لینک از منوی کناری + کارت داشبورد) با **۱۴ صفحهٔ مستقل دارای URL** — CRUD واقعی روی دوره‌ها، پایه‌ها، شاخه‌ها، زمینه‌ها، رشته‌ها، درس‌ها، کتاب‌ها، نسخه‌ها، ارتباط‌ها، سال‌های تحصیلی (+ کپی ساختار از سال قبل)، وضعیت اعتبار، گونه‌های مخاطب، کتاب‌های آزمایشی/منطقه‌ای، آرشیو — با حذف وابستگی‌محور (پیام شمارش وابستگی‌ها؛ CASCADE خام ممنوع)، آرشیو/بازیابی، آپلود PDF نسخه (SHA256؛ هرگز ready نمی‌کند)، جست‌وجو/فیلتر/مرتب‌سازی/صفحه‌بندی، audit کامل before/after در `admin_action_logs`، و بازتاب فوری تغییرات در انتخاب‌گر دانش‌آموز.

## ۱۰) فایل‌های تغییرکرده/جدید در این فاز

**بک‌اند جدید:** `app/api/admin_catalog.py`، `app/services/admin_catalog_service.py`، `alembic/versions/c9d0e1f2a3b4_admin_catalog_management.py`، `tests/test_admin_academic_profile_isolation.py`، `tests/test_admin_catalog_management.py`، `scripts/catalog_pg_migration_check.py`، `scripts/catalog_report_counts.py` (توسعه)
**بک‌اند ویرایش:** `app/api/admin_users.py`، `app/services/admin_user_service.py`، `app/api/academic_profile.py`، `app/services/academic_profile_service.py`، `app/models/curriculum.py`، `app/models/catalog.py`، `alembic/versions/b8c9d0e1f2a3…` (رفع drift)، `tests/test_education_catalog_1405_1406.py`، `tests/test_phase1_governance.py` (به‌روزرسانی به قرارداد بسته‌شده)
**فرانت جدید:** `lib/adminCatalog.ts`، `components/AdminCatalogManager.tsx`، `components/AdminCatalogPage.tsx`، `components/AdminCatalogArchive(+Body).tsx`، `components/AdminEducationIndex.tsx`، `app/admin/education/**` (۱۵ صفحه)، `tests/AdminCatalogManager.test.tsx`
**فرانت ویرایش:** `components/AdminUsersPanel.tsx`، `components/AdminRolesQuotasPanel.tsx`، `components/AdminUserDetailPanel.tsx`، `components/AdminOverviewPanel.tsx`، `components/AdminSideNav.tsx`، `components/AcademicProfilePicker.tsx`، `components/AcademicProfileGate.tsx`، `lib/academicProfile.ts`، `app/globals.css`

## ۱۱) Rollback (اصلاح‌شده در بازبینی نهایی — زنجیرهٔ واقعی: `a04a… → … → e1f2a3b4c5d6 → b8c9d0e1f2a3 → c9d0e1f2a3b4`)

- **وضعیت head:** `c9d0e1f2a3b4` (تک head).
- **والد `b8c9d0e1f2a3` برابر `e1f2a3b4c5d6` است** — پس دستور بازگشت باید به revision **مقصد** اشاره کند، نه به خودِ revision حذف‌شونده:
  - فقط حذف ستون‌های مدیریتی (undo آخرین migration): `alembic downgrade b8c9d0e1f2a3`
  - حذف کامل migration کاتالوگ + ستون‌های مدیریتی با **یک دستور**: `alembic downgrade e1f2a3b4c5d6`
- هر دو دستور روی PostgreSQL دورریختنی اعتبارسنجی شد (`scripts/rollback_ladder_check.py`): رکورد کاربر واقعی سالم ماند، جداول کاتالوگ حذف و با re-upgrade + seed بازسازی شدند. دادهٔ کاربران هرگز حذف نمی‌شود.
- **هرگز روی دیتابیس دارای دادهٔ واقعی اجرا نشود** — فقط روی instance دورریختنی/استیجینگ.
- کد: `git checkout -- <فایل‌های ویرایش‌شده>` + حذف فایل‌های جدید طبق بند ۱۰.

## ۱۲) تست‌های انجام‌نشده (صادقانه)

- تم تاریک UI (فقط تم پیش‌فرض روشن در Playwright اجرا شد).
- مرورگرهای غیر از Chromium.
- بار/عملکرد (pagination روی مجموعه‌های خیلی بزرگ).
