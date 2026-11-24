# مدیریت نظام آموزشی و کاتالوگ درسی — سند پیاده‌سازی (ADDENDUM)

> **تاریخ:** ۲۰۲۶-۱۱-۲۳ · **وضعیت:** `PASS — ADMIN EDUCATION CATALOG MANAGEMENT READY`
> بخش مستقل پنل مدیریت برای CRUD کامل اجزای نظام آموزشی ایران با حفظ تاریخچه، audit و RBAC.

## ۱) صفحات مدیریت (URL مستقل، قابل دسترسی مستقیم)

ورود: از **منوی کناری پنل** (لینک مستقل «مدیریت نظام آموزشی و کاتالوگ درسی») و از **کارت داشبورد** (`/admin` → نمای کلی).

| # | صفحه | URL | موجودیت |
|---|---|---|---|
| ۱ | مدیریت دوره‌های تحصیلی | `/admin/education/cycles` | cycles |
| ۲ | مدیریت پایه‌ها و کلاس‌ها | `/admin/education/grades` | grades |
| ۳ | مدیریت شاخه‌ها | `/admin/education/branches` | branches |
| ۴ | مدیریت زمینه‌ها | `/admin/education/grounds` | grounds |
| ۵ | مدیریت رشته‌ها | `/admin/education/programs` | fields |
| ۶ | مدیریت درس‌ها و مواد درسی | `/admin/education/subjects` | subjects |
| ۷ | مدیریت کتاب‌های درسی | `/admin/education/textbooks` | textbooks |
| ۸ | مدیریت نسخه‌های کتاب | `/admin/education/editions` | editions (+PDF) |
| ۹ | مدیریت ارتباط کتاب‌ها با پایه‌ها و رشته‌ها | `/admin/education/links` | links |
| ۱۰ | مدیریت سال‌های تحصیلی | `/admin/education/years` | academic-years (+کپی ساختار) |
| ۱۱ | مدیریت وضعیت اعتبار رشته‌ها | `/admin/education/validity` | program-availability |
| ۱۲ | مدیریت گونه‌های کتاب و مخاطبان | `/admin/education/audiences` | نمایهٔ textbooks/audience_variant |
| ۱۳ | مدیریت کتاب‌های آزمایشی و منطقه‌ای | `/admin/education/special` | نمایهٔ textbooks/implementation_status |
| ۱۴ | آرشیو اطلاعات حذف‌شده یا غیرفعال | `/admin/education/archive` | نمایهٔ بین‌موجودیتی |

معماری: یک کامپوننت عمومی `AdminCatalogManager` (جدول + فرم + فیلتر + مودال‌ها) به‌ازای هر موجودیت با پیکربندی تایپ‌دار در `lib/adminCatalog.ts` — هر ماژول page wrapper نازک خودش را دارد؛ هیچ صفحهٔ غول‌آسایی وجود ندارد.

## ۲) APIهای مدیریتی (همه زیر محافظ `require_admin`)

```
GET    /api/v1/admin/catalog/overview                       شمارش کل موجودیت‌ها
GET    /api/v1/admin/catalog/archive                        آرشیو بین‌موجودیتی
GET    /api/v1/admin/catalog/{entity}                       فهرست: q، فیلترها، sort، direction، page، page_size، include_archived
POST   /api/v1/admin/catalog/{entity}                       ایجاد
GET    /api/v1/admin/catalog/{entity}/{id}                  جزئیات
PATCH  /api/v1/admin/catalog/{entity}/{id}                  ویرایش (قبل/بعد در audit)
DELETE /api/v1/admin/catalog/{entity}/{id}                  حذف دائمی — فقط با صفر وابستگی
GET    /api/v1/admin/catalog/{entity}/{id}/dependencies     شمارش وابستگی‌ها برای پیام تأیید
POST   /api/v1/admin/catalog/{entity}/{id}/archive          آرشیو/غیرفعال
POST   /api/v1/admin/catalog/{entity}/{id}/restore          بازیابی
POST   /api/v1/admin/catalog/academic-years/{id}/copy-structure   کپی اولیهٔ ساختار سال مبدأ → مقصد
POST   /api/v1/admin/catalog/editions/{id}/pdf              آپلود/جایگزینی PDF (multipart، SHA256)
```
`{entity}` ∈ cycles, grades, branches, grounds, fields, subjects, textbooks, links, academic-years, editions, program-availability.

## ۳) قواعد حذف امن

- قبل از حذف، `dependencies` شمارش می‌شود و در مودال نمایش داده می‌شود («این پایه به N رکورد وابسته متصل است…»).
- اگر مجموع وابستگی‌ها > 0 → **409 با پیام فارسی**؛ راه جایگزین: آرشیو/غیرفعال‌سازی.
- حذف با CASCADE خام بدون مجوز صریح وجود ندارد (FKهای خطرناک CASCADE ندارند به‌جز link↔textbook داخلی).
- آرشیو: `is_active=false` (دوره/پایه/شاخه/زمینه/رشته/درس) یا `archived_at` (کتاب کاتالوگ) — تاریخچهٔ دانش‌آموزان و ارجاعات حفظ می‌شود؛ فقط انتخاب‌های جدید متوقف می‌شود.

## ۴) قواعد اعتبارسنجی (سمت سرور، پیام فارسی)

- شمارهٔ پایهٔ تکراری/خارج از ۱–۱۲ → 409/422؛ اتصال پایه به دورهٔ نامعتبر → 422.
- زمینه فقط برای شاخه‌های هنرستانی؛ رشته باید به همان شاخه/زمینه تعلق داشته باشد (ادغام هویت برنامه‌های فنی‌وحرفه‌ای و کاردانش ممکن نیست — کد یکتای global).
- ترکیب‌های تکراری (کد یکتا، شمارهٔ پایه، (رشته،سال)) → 409.
- slug کتاب به‌طور خودکار از عنوان ساخته می‌شود؛ `national_code` فقط در صورت وجود واقعی (NULL = نامشخص، هرگز ساختگی).
- **قانون انتشار حفظ شد:** وضعیت `ready` فقط توسط خط پردازش کتاب؛ آپلود PDF ادمین status را ready نمی‌کند و تلاش دستی → 422.

## ۵) سال تحصیلی و کپی ساختار

- ایجاد سال جدید؛ کپی اولیه از سال قبل: `ProgramAvailability` + `CatalogCourseTextbook` ها با scope_code بازنویسی‌شده کپی می‌شوند؛ رکوردهای سال مبدأ دست‌نخورده؛ اجرای دوباره کپی صفر تکرار می‌سازد (تست‌شده: ۳۰۳ لینک + ۱۱۸ وضعیت، بار دوم ۰).

## ۶) RBAC — ماتریس دسترسی

| نقش | مشاهده کاتالوگ | ایجاد/ویرایش/حذف/آرشیو | آپلود PDF | کپی سال | پروفایل تحصیلی دانش‌آموز |
|---|---|---|---|---|---|
| super_admin / admin (توکن یا session) | ✓ | ✓ | ✓ | ✓ | فقط مشاهده |
| moderator | ✗ (403) | ✗ | ✗ | ✗ | فقط مشاهدهٔ کاربران |
| teacher | ✗ (403) | ✗ | ✗ | ✗ | ✗ |
| student / ناشناس | ✗ (401/403) | ✗ | ✗ | ✗ | فقط خودش |

- **مجوز مستقل `can_manage_education_catalog`** (بازبینی اصلاحی §۲): مدیریت کاتالوگ دیگر از `can_read_users` (مجوز مشاهدهٔ کاربران در سطح moderator) استفاده نمی‌کند؛ مجوز اختصاصی فقط به `admin` و `super_admin` می‌دهد و moderator/teacher/student را رد می‌کند.
- `require_admin` در سطح router (401 ناشناس، 403 برای user session غیرمدیر) + `can_manage_education_catalog` در هر endpoint → دور زدن UI از مسیر HTTP ممکن نیست.
- تست RBAC جامع: هر ۶ عملیات جهش‌دهنده (ایجاد/ویرایش/حذف/آرشیو/بازیابی/آپلود PDF) × معلم/دانش‌آموز (403) × مدیر (موفق) × ناشناس (401) + ماتریس unit-level — `test_catalog_rbac_dedicated_permission_blocks_teacher_student_anonymous`.
- تغییر وضعیت رسمی رشته (در program-availability) کاملاً مستقل از انتخاب دانش‌آموز است؛ آرشیو رشته، انتخاب‌های جدید را می‌بندد ولی پروفایل‌های تاریخی را حذف/تغییر نمی‌دهد (تست‌شده).

## ۷) Audit Log

هر عملیات در `admin_action_logs` (موجود، بازاستفاده‌شده) با:
`actor`، `action=catalog.{entity}.{create|update|delete|archive|restore|pdf-upload|copy-structure}`، `target=catalog:{entity}:{id}`، `payload_json={entity, entity_label, entity_id, before, after, result, note?}`، timestamp.
- مقادیر before/after کامل (snapshot ستون‌های متن)؛ هیچ کلید API/رمز/محرمانه‌ای ثبت نمی‌شود.
- مشاهدات: تست‌ها وجود رکوردهای `catalog.fields.create` و `catalog.program-availability.update` و `catalog.textbooks.update` را assert می‌کنند.

## ۸) انتخاب‌گر دانش‌آموز — بازتاب تغییرات

- رشتهٔ جدید فعال ادمین → بلافاصله در `GET /account/academic-profile` (options) ظاهر می‌شود (تست‌شده).
- آرشیو رشته → از گزینه‌های جدید حذف می‌شود؛ پروفایل تاریخی دانش‌آموز دست‌نخورده (تست‌شده).
- بازیابی → گزینه برمی‌گردد (تست‌شده).

## ۹) تست‌ها

- بک‌اند: `tests/test_admin_catalog_management.py` — ۷ تست (شامل تست جامع RBAC) که کل فهرست اجباری §۱۸ را پوشش می‌دهند (ایجاد/ویرایش/حذف امن پایه، شاخه/زمینه/رشته + اعتبار + audit، درس، کتاب + کد رسمی + لینک چندرشته‌ای + حذف ارتباط، نسخه + PDF + منع ready، سال جدید + کپی + idempotency + جلوگیری از تکرار، RBAC + به‌روزرسانی انتخاب‌گر + عدم تغییر پروفایل شخصی).
- فرانت: `tests/AdminCatalogManager.test.tsx` — ۵ تست (رندر فهرست، ایجاد AJAX، مودال حذف با شمارش وابستگی + بلاک حذف مخرب، دکمهٔ آرشیو، 401→onUnauthorized).
- Playwright واقعی (مرورگر): ۹/۹ — جزئیات در `IRAN_EDUCATION_CATALOG_FINAL_REVIEW.md` §۷.
- رگرسیون کامل سبز: pytest ۴۹۶/۱skip، vitest ۹۵/۹۵، tsc 0، lint 0، build ✓، PG ۸ مرحله ✓.

## ۱۰) Rollback (اصلاح‌شده — زنجیرهٔ واقعی migration)

زنجیره: `e1f2a3b4c5d6 → b8c9d0e1f2a3 (کاتالوگ ۱۴۰۵–۱۴۰۶) → c9d0e1f2a3b4 (مدیریت ادمین، head)` — والد `b8c9d0e1f2a3` همان `e1f2a3b4c5d6` است، پس دستور به revision **مقصد** اشاره می‌کند:

```bash
# فقط undo آخرین migration (حذف ستون‌های مدیریتی: is_active/archive/source_url/course_kind/…):
alembic downgrade b8c9d0e1f2a3

# حذف کامل migration کاتالوگ + ستون‌های مدیریتی (یک دستور، بازگشت به والد):
alembic downgrade e1f2a3b4c5d6
```

هر دو روی PostgreSQL دورریختنی اعتبارسنجی شد (`scripts/rollback_ladder_check.py`): رکورد کاربر سالم، جداول کاتالوگ حذف/بازسازی، grades حفظ شد. **روی دیتابیس دارای دادهٔ واقعی اجرا نشود.**
- کد: برگرداندن فایل‌های ویرایش‌شده + حذف فایل‌های جدید (فهرست کامل در FINAL_REVIEW §۱۰).
- داده: audit logs در `admin_action_logs` می‌مانند؛ رکوردهای آرشیوشده با restore بازمی‌گردند.
