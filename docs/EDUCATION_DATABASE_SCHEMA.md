# اسکیمای پایگاه دادهٔ آموزشی درسیار

> نسخه: کاتالوگ ۱۴۰۵–۱۴۰۶ · Migration: `b8c9d0e1f2a3_education_catalog_1405_1406` (برگشت‌پذیر، روی head قبلی `e1f2a3b4c5d6`)

## ۱) نگاشت موجودیت‌های مفهومی به جداول واقعی

اصل حاکم: «ابتدا مدل‌های فعلی را بررسی کن و از ایجاد مدل تکراری خودداری کن.» بنابراین ساختار موجود بازاستفاده شده و فقط موجودیت‌های واقعاً مفقود اضافه شده‌اند:

| موجودیت موردنیاز | پیاده‌سازی واقعی | وضعیت |
|---|---|---|
| AcademicYear | `academic_years` (موجود) | سال `1405-1406` توسط Seed |
| EducationStage | `education_cycles` (موجود) | ۳ دوره |
| Grade | `grades` (موجود) | ۱۲ پایه با اتصال دوره |
| Track (شاخه) | `education_branches` (موجود) | ۳ شاخه |
| Field (زمینه — فقط هنرستانی) | **جدید** `education_grounds` | ۸ رکورد (۲ شاخه × ۴ زمینه) |
| Program (رشته) | `fields_of_study` (موجود + ستون جدید `ground_id`) | ۴ نظری + ۱۱۸ هنرستانی |
| Course (درس) | `subjects` (موجود) | درس‌های کاتالوگ توسط Seed |
| Textbook (عنوان اصلی) | **جدید** `catalog_textbooks` | رکورد عنوان بدون PDF |
| TextbookEdition (نسخه) | `books` (موجود + ستون جدید `catalog_textbook_id`) | هر چاپ/سال = یک سطر |
| CourseTextbook | **جدید** `catalog_course_textbooks` + `book_curriculum_links` (موجود) | عنوان↔پایه/شاخه/رشته |
| ProgramAvailability | **جدید** `program_availability` | وضعیت اعتبار به‌ازای سال |
| StudentAcademicProfile | **جدید** `student_academic_profiles` | پروفایل خود-خدمتی دانش‌آموز |
| CatalogSource / CatalogImportRun | **جدید** `catalog_sources` / `catalog_import_runs` | منشأ و ممیزی واردات |

**کد رسمی ملی ≠ شناسهٔ داخلی:** شناسه‌های داخلی (`code`/`slug`) صرفاً کلید پایدار داخلی‌اند؛ کد رسمی تنها در `catalog_textbooks.national_code` و فقط وقتی مالک ارائه کند ذخیره می‌شود.

## ۲) جداول جدید

### education_grounds
`id, branch_id→education_branches, code, title, sort_order, is_active` — Unique `(branch_id, code)`. فقط برای شاخه‌های فنی‌وحرفه‌ای/کاردانش.

### catalog_textbooks
`id, slug(UNIQUE), title_fa, title_en, national_code(NULL=نامشخص), grade_id(NULL=پایهٔ راستی‌آزمایی‌نشده), subject_id, academic_year_id, textbook_kind(student_book|workbook|supplementary|periodical|teacher_guide), audience_variant(general|girls|boys|religious_minority), audience_scope, implementation_status(confirmed|experimental|regional_pilot|needs_verification), geographic_scope, alternative_group, validity_status(active|needs_verification|unknown), verification_note, catalog_source_id, verified_at, timestamps` + چهار CheckConstraint روی enumها.

### catalog_course_textbooks
`id, textbook_id→catalog_textbooks(CASCADE), academic_year_id, grade_id, branch_id, field_of_study_id, scope_code, is_mandatory, note` — Unique `(textbook_id, scope_code)`؛ `scope_code` کلید پایدار scope است تا یکتایی با NULL در PostgreSQL و SQLite یکسان کار کند (همان الگوی `book_curriculum_links`). CheckConstraint: رشته بدون شاخه ممنوع.

### program_availability
`id, field_of_study_id(CASCADE), academic_year_id, validity_status(active|stopped_development|redesigned|needs_verification|unknown), evidence_note, catalog_source_id, verified_at, timestamps` — Unique `(field_of_study_id, academic_year_id)`.

### student_academic_profiles
`id, user_id→users(CASCADE, UNIQUE), grade_id, branch_id, ground_id, field_of_study_id, academic_year_id, timestamps` + CheckConstraintهای «رشته بدون شاخه ممنوع» و «زمینه بدون شاخه ممنوع».

### catalog_sources / catalog_import_runs
منشأ داده (کلید `darsyar_iran_education_catalog_1405-1406`) و ممیزی هر اجرای واردات (`status, stats JSON, started_at, finished_at`).

## ۳) ستون‌های افزودهٔ روی جداول موجود

- `fields_of_study.ground_id` (nullable → `education_grounds.id`) — فقط رشته‌های هنرستانی
- `books.catalog_textbook_id` (nullable → `catalog_textbooks.id`) — اتصال نسخهٔ واقعی به عنوان کاتالوگ؛ NULL برای کتاب‌های قبل از کاتالوگ

## ۴) روابط سلسله‌مراتبی نهایی

```
academic_years
└── education_cycles (دوره)
    └── grades (۱۲ پایه)
        └── education_branches (شاخه؛ فقط پایهٔ ۱۰+)
            ├── نظری: field_of_study (رشته، ground_id=NULL)
            └── فنی‌وحرفه‌ای/کاردانش: education_grounds (زمینه)
                     └── field_of_study (رشته، ground_id الزامی)
                        └── catalog_course_textbooks (ارتباط کتاب)
                            └── catalog_textbooks (عنوان یکتا)
                                └── books (نسخهٔ واقعی با PDF، از طریق catalog_textbook_id)
```

کتاب‌های عمومی (ابتدایی/متوسطه اول) بدون هیچ اتصال اجباری به شاخه/رشته ثبت می‌شوند (سطر ارتباط با `branch_id/field_of_study_id = NULL` و فقط پایه + سال).

## ۵) سیاست‌های ایمنی داده

- Migration جدید و برگشت‌پذیر است؛ هیچ migration قبلی بازنویسی/حذف نشده؛ هیچ دادهٔ کاربر حذف نمی‌شود؛ در downgrade فقط جداول/ستون‌های جدید حذف می‌شوند.
- Production فقط با Alembic (`alembic upgrade head`)؛ `create_all` فقط در تست‌های sandbox استفاده شده است.
- Seed نسخه‌بندی‌شده: هر رکورد به `academic_year 1405-1406` و `catalog_source` گره خورده است؛ ورود سال بعد، رکورد این سال را تخریب نمی‌کند (سال بخشی از کلید scope است).
- Re-run سطح دوم: «اولین اجرا ۲۱۱ کتاب ساخت؛ اجرای دوباره صفر» — تضمین‌شده با تست.
