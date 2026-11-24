# گزارش اصلاحات نهایی مدیریت کاتالوگ ادمین (Final Correction Review)

> **تاریخ:** ۲۰۲۶-۱۱-۲۳
> ## نتیجه: `PASS — ADMIN CATALOG READY FOR STAGING`

---

## ۱) اصلاح Rollback — زنجیرهٔ Migration بررسی و تصحیح شد

**بررسی واقعی زنجیره:**

| revision | عنوان | down_revision (والد) |
|---|---|---|
| `c9d0e1f2a3b4` | admin catalog management | `b8c9d0e1f2a3` |
| `b8c9d0e1f2a3` | education catalog 1405–1406 | **`e1f2a3b4c5d6`** ✓ (تأیید از خود فایل migration) |
| `e1f2a3b4c5d6` | align flashcard study sessions user_id | `d0e1f2a3b4c5` |

- **وضعیت head:** `c9d0e1f2a3b4 (head)` — تک head (خروجی `alembic heads`).
- **دستور صحیح:** چون والد `b8c9d0e1f2a3` برابر `e1f2a3b4c5d6` است، حذف migration کاتالوگ با بازگشت به revision **مقصد** انجام می‌شود:
  - `alembic downgrade e1f2a3b4c5d6` → با **یک دستور** هر دو migration کاتالوگ (b8c9 + c9d0) را حذف می‌کند.
  - `alembic downgrade b8c9d0e1f2a3` → فقط undo آخرین migration (ستون‌های مدیریتی).
  - (اشاره‌کردن به خودِ `b8c9d0e1f2a3` به‌عنوان مقصدِ «حذف کاتالوگ» اشتباه بود و در هر دو سند اصلاح شد.)
- **اعتبارسنجی — فقط روی PostgreSQL دورریختنی** (`scripts/rollback_ladder_check.py`؛ طبق D-002 و بدون تماس با هر دیتابیس واقعی/توسعه‌ای):
  1. مهاجرت تا `b8c9d0e1f2a3` + درج رکورد کاربر واقعی → upgrade تا head → اجرای seedها
  2. `alembic downgrade e1f2a3b4c5d6` → نتیجه: `version_num = e1f2a3b4c5d6`، **رکورد کاربر سالم**، جداول کاتالوگ حذف‌شده، `grades` (۱۲ ردیف) حفظ‌شده
  3. `alembic upgrade head` + اجرای مجدد seed → بازسازی کامل، کاربر همچنان سالم، بدون تکرار
- مستندات Rollback در دو سند (`IRAN_EDUCATION_CATALOG_FINAL_REVIEW.md` §۱۱ و `ADMIN_EDUCATION_CATALOG_MANAGEMENT.md` §۱۰) با نردبان صحیح و هشدار «هرگز روی دیتابیس دارای دادهٔ واقعی اجرا نشود» به‌روزرسانی شد.

## ۲) بازبینی RBAC — مجوز مستقل جایگزین `can_read_users` شد

**یافته:** APIهای مدیریت کاتالوگ از `permissions.can_read_users` استفاده می‌کردند که فقط `rank ≥ moderator (40)` است — یعنی مجوز «مشاهدهٔ پروندهٔ کاربران»، نه مدیریت کاتالوگ ملی؛ moderator به‌اشتباه مجاز می‌شد.

**اصلاح:** مجوز مستقل در `app/services/permissions.py`:

```python
def can_manage_education_catalog(actor: AdminActor) -> bool:
    # managing the national catalog is admin-only; a student's own academic
    # placement stays student-owned self-service data either way
    return actor.rank >= ROLE_RANKS["admin"]   # admin(50) و super_admin(60)
```

- در `app/api/admin_catalog.py` جایگزین `can_read_users` شد (خطای 403 با پیام فارسی).
- `require_admin` در سطح router دست‌نخورده ماند (ناشناس → 401؛ user session غیرمدیر → 403).

**ماتریس اعمال‌شده (تست unit + HTTP):**

| نقش | ایجاد | ویرایش | حذف | آرشیو | بازیابی | آپلود PDF | مشاهده |
|---|---|---|---|---|---|---|---|
| super_admin | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| admin | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| moderator | ✗ 403 | ✗ 403 | ✗ 403 | ✗ 403 | ✗ 403 | ✗ 403 | ✗ 403 |
| teacher | ✗ 403 | ✗ 403 | ✗ 403 | ✗ 403 | ✗ 403 | ✗ 403 | ✗ 403 |
| student | ✗ 403 | ✗ 403 | ✗ 403 | ✗ 403 | ✗ 403 | ✗ 403 | ✗ 403 |
| ناشناس | ✗ 401 | ✗ 401 | ✗ 401 | — | — | — | ✗ 401 |

**تست جامع اجرا شد:** `tests/test_admin_catalog_management.py::test_catalog_rbac_dedicated_permission_blocks_teacher_student_anonymous` — هر ۶ عملیات جهش‌دهنده (ایجاد cycle، ویرایش grade، حذف امن ground، آرشیو، بازیابی، آپلود PDF) × {معلم، دانش‌آموز} → 403؛ × مدیر → 200/201؛ × ناشناس → 401؛ + ماتریس unit-level پنج نقش. نتیجه: **PASS**.

**نکتهٔ کشف‌شده در تست:** cookie نشست کنسول ادمین (HttpOnly `iran_tutor_admin`) بر bearer کاربر معلم **پیش‌أبولت** است (رفتار کل پنل ادمین: هرکس cookie ادمین داشته باشد اپراتور کنسول است)؛ بنابراین تست‌های RBAC با clientهای ایزولهٔ بدون cookie اجرا می‌شوند تا دقیقاً RBAC و نه session-precedence آزموده شود.

## ۳) حفظ تصمیم‌های محصول

- **مدیر مالک کاتالوگ عمومی است** — همهٔ عملیات CRUD/آرشیو/بازیابی فقط با `can_manage_education_catalog` (admin+) باز.
- **دانش‌آموز مالک پروفایل شخصی** — هیچ endpoint کاتالوگی مسیر نوشتن به `student_academic_profiles` ندارد؛ تست ایزولاسیون قبلی (ادمین 422 روی فیلدهای تحصیلی، دانش‌آموز self-service کامل) همچنان سبز است.
- **هیچ تأیید/تغییر اجباری پروفایل** — مدیریت کاتالوگ فقط موجودیت‌های عمومی را تغییر می‌دهد.
- **تاریخچه/دادهٔ یادگیری محفوظ** — حذف وابستگی‌دار (409 با شمارش)، آرشیو به‌جای حذف، تست صریح «پروفایل تاریخی پس از آرشیو رشته دست‌نخورده» و «گفت‌وگوها پس از تغییر پایه حفظ می‌شوند».

## ۴) رگرسیون کامل پس از اصلاحات (نتایج واقعی)

| دروازه | نتیجه |
|---|---|
| Backend pytest (کل سوئیت) | **۴۹۷ passed / ۱ skipped** (شامل تست RBAC جدید) |
| Frontend Vitest | **۱۳ فایل / ۹۵ تست** پاس |
| ESLint | exit 0 |
| TypeScript | exit 0 |
| Production Build | ✓ |
| PostgreSQL rollback-ladder (دورریختنی) | ✓ ROLLBACK_LADDER_VALIDATED |

## ۵) فایل‌های تغییرکرده در این اصلاح

- `app/services/permissions.py` — افزودن `can_manage_education_catalog`
- `app/api/admin_catalog.py` — استفاده از مجوز مستقل به‌جای `can_read_users`
- `tests/test_admin_catalog_management.py` — تست جامع RBAC (۶ عملیات × ۳ نقش + ماتریس unit)
- `docs/IRAN_EDUCATION_CATALOG_FINAL_REVIEW.md` §۱۱، `docs/ADMIN_EDUCATION_CATALOG_MANAGEMENT.md` §۶ و §۱۰ — اصلاح Rollback/RBAC
- `scripts/rollback_ladder_check.py` (جدید) — اعتبارسنجی نردبان rollback روی PG دورریختنی

## ۶) نتیجه

`PASS — ADMIN CATALOG READY FOR STAGING`
