# REDESIGN — گزارش فاز ۰۶: مرکز کنترل مدیریت، Navigation و یکپارچه‌سازی AJAX

> **تاریخ:** ۲۰۲۶-۱۱-۲۴ · **شاخه:** `main` (بدون commit؛ تغییرات در working tree) · **پایه:** `7db4f35`
> **حکم نهایی: PARTIAL — ADMIN CORE COMPLETE** (همهٔ معیارهای اصلی Navigation/URL/Dashboard/AJAX/RBAC/Secrets/Regression با شواهد واقعی تأیید شد؛ فهرست کامل موارد باقی‌مانده در §۱۷ صریح ثبت شده است)

## ۱) خلاصهٔ اجرایی

کاوش اولیه (فقط از کد و تست، نه مستندات) نشان داد پنل ادمین از قبل یک Control Center با ۱۵ تبِ URL-driven دارد و KPIهای داشبورد کاملاً از `GET /api/v1/admin/overview` واقعی می‌آیند — هیچ KPI ساختگی وجود نداشت. شکاف‌های واقعی این بود: (۱) آیتم‌های ناوبری `<button>` بودند نه لینک واقعی، (۲) فیلترهای جست‌وجو/صفه‌بندی/مرتب‌سازی در چهار پنل فقط state محلی بودند یا فقط نوشته می‌شدند و هرگز از URL خوانده نمی‌شدند (refresh فیلترها را می‌باخت)، (۳) قابلیت پادکست API مدیریتی داشت ولی هیچ نمای مدیریتی نداشت، (۴) ۱۵ mutation حساس (کتاب، ارائه‌دهنده، مسیر مدل، سهمیه، billing، تنظیمات runtime) هیچ ردیف Audit نداشتند، (۵) دو کارت KPI مقصد کلیک نداشتند. در این فاز دقیقاً همین شکاف‌ها بسته شد و هیچ قابلیتی بازنویسی نشد.

## ۲) Git Audit و وضعیت اولیه

```text
git status --short --branch  →  ## main · 20 فایل M از فازهای قبل + 9 untracked (فاز ۰۵) — همه حفظ شدند
git log -1 --oneline         →  7db4f35 Baseline: iran-tutor phase04B snapshot
git diff --cached            →  خالی (هیچ‌چیز stage نشده)
```
فاز 06 فقط به ۹ فایل مشترک‌نشده با فازهای قبل دست زد؛ تنها فایل هم‌پوشان `app/admin/page.tsx` بود که تغییرش یک import + یک بلوک رندر اضافه است (تفاضل کامل در patch فاز ۰۶ موجود است).

## ۳) Inventory کامل قابلیت‌های مدیریتی (از کد واقعی)

| Capability | API موجود | Route موجود | Permission | مقصد URL | وضعیت |
|---|---|---|---|---|---|
| Dashboard / KPI | `GET /api/v1/admin/overview` (aggregate واقعی) | `/admin?tab=overview` | `require_admin` | `/admin?tab=overview` | EXISTS (کلیک‌پذیری تکمیل شد) |
| Curriculum & Books | `/admin/books*`، `/admin/catalog/{11 entity}` | tab books + ۱۴ صفحهٔ `/admin/education/*` | `require_admin` + `can_manage_education_catalog` | هر دو مسیر | EXISTS |
| Ingestion & Review | `/admin/kb/jobs*`، `/books/{id}/pages/{idx}`، reindex/reprocess | tab kb + صف بازبینی در overview | `require_admin` | `/admin?tab=kb` | EXISTS |
| Users | `/admin/users` (q/role/status/plan/page سمت سرور) + `/admin/users/{id}/{sessions,credits,audit,password,...}` | tab users (AdminUsersPanel) | `can_read_users` / `can_manage_user` / `can_delete_user` / `can_assign_role` + reauth | `/admin?tab=users&q=…&status=…&page=…` | EXISTS (read-back URL اضافه شد) |
| Roles & Sessions | `/admin/users/roles`، `/users/{id}/sessions/{sid}` DELETE، revoke-all | tabs users/roles | `can_manage_sessions`، reauth | tabs | EXISTS |
| Providers & Models | `/admin/providers*`، `/providers/{id}/test` | tab providers | `require_admin` | `/admin?tab=providers` | EXISTS (audit جدید) |
| Model Routing | `GET/PUT/DELETE /admin/routes*` | همان tab providers | `require_admin` | همان | EXISTS (audit جدید) |
| Capabilities & Skills | `/admin/capabilities*`، `/admin/skills*` (+rollback/test) | tabs capabilities/skills | `require_admin` | tabs | EXISTS |
| Quotas & Plans | `/admin/quotas*`، `/admin/billing*`، `/billing/plans/{code}` | tabs roles/plans | `require_admin` | tabs | EXISTS (audit جدید) |
| Payments | تراکنش‌ها در `/overview.recent_transactions`، ثبت از مسیر کاربر | کارت در overview، tab plans | `require_admin` | overview/plans | EXISTS (API پرداخت ادمین مستقل وجود ندارد → نمای جدید نساخته شد) |
| AI Audit & Quality | `/admin/audit-logs{,/summary,/{id},/{id}/flag}` | tab observability | `require_admin` (+`can_read_audit` برای audit کاربران) | `/admin?tab=observability&feature=…&page=…` | EXISTS (URL contract اضافه شد) |
| Jobs & Workers (KB) | `/admin/kb/jobs`، `cancel`، `run` | tab kb | `require_admin` | `/admin?tab=kb` | EXISTS |
| Podcasts (عملیاتی) | `/admin/podcasts/stats`، `/admin/podcasts/episodes?status=` | **جدید: tab podcasts** | `require_admin` | `/admin?tab=podcasts&status=…` | NEEDS_UI → **در همین فاز پر شد (read-only)**؛ retry ادمین: BACKEND_MISSING (§۱۷) |
| Health & Observability | `/health`، `/api/v1/system/status`، `overview.system` | tab overview | public/`require_admin` | overview | EXISTS |
| Settings | `/admin/settings{,/reset,/test-ai,/test-vector,/test-sms}`، `/admin/preferences` | tabs integrations/appearance | `require_admin` | tabs | EXISTS (audit جدید) |
| Exams | `overview.counts.exams_total`، خواندن per-user در `phase5_admin` | overview/deep_learning | `require_admin` | tabs موجود | EXISTS (تب مستقل لازم نداشت) |
| Mistakes / Deep Solve / Mastery | `/admin/users/{id}/{mistakes,deep-solve-sessions}`، `/admin/mastery/*`، `/admin/mastery/evidence` | tab deep_learning | `require_admin` | `/admin?tab=deep_learning` | EXISTS |
| Flashcards | `/admin/flashcards/{stats,decks,reports}`، moderation | tab flashcards | `require_admin` | `/admin?tab=flashcards&source=…&public=…` | EXISTS (URL contract اضافه شد) |
| Notebooks (مطالعهٔ غنی) | `/admin/phase6/living-book`، `/audio-cache` | tab rich_study | `require_admin` | tab | EXISTS |
| Global Search | `/admin/search?q=&category=` | سرچ سراسری سربر | `require_admin` | همان | EXISTS |

**خلاصهٔ وضعیت‌ها:** EXISTS×20 · NEEDS_UI→پرشده×1 (Podcasts) · BACKEND_MISSING×1 (retry ادمینِ پادکست — مستند، ساختگی نساخته شد) · NOT_APPLICABLE×0.

## ۴) نقشهٔ Routeها و URLها

- **تب‌های `/admin` (۱۶ کلید):** `overview, books, kb, podcasts(جدید), flashcards, deep_learning, rich_study, users, roles, providers, integrations, capabilities, skills, plans, observability, appearance` — همه با `/admin?tab=<key>`؛ whitelist در `parseAdminTabParam`.
- **Routeهای مستقل (حفظ شدند):** `/admin/education` + ۱۴ زیرصفحه (`cycles…archive`)، `/admin/observability`، `/admin/providers`، `/admin/roles`، `/admin/users/[id]`.
- **فیلترها در URL (refresh-safe):** users → `q,status,role,plan,page` · catalog → `page,q,sort,direction` · observability → `feature,status,flagged,user,days,page` · flashcards → `source,public` · podcasts → `status`.

## ۵) Navigation و تغییرات UX

1. آیتم‌های `AdminSideNav` از `<button onClick>` به **`<Link href="/admin?tab=…">`** تبدیل شدند (باز‌شدن در تب جدید، prefetch، href واقعی؛ onClick فقط برای بستن drawer و side-effect فچ‌های هر تب حفظ شد). لینک آموزشی هم `Link` شد.
2. تب **«پادکست‌های آموزشی»** به گروه «پردازش دانش» اضافه شد با آیکن `Mic`.
3. Active state همچنان از URL می‌آید (`?tab=`) و اکنون برای آیتم‌های `<a>` با `aria-current="page"` صحت‌سنجی شده است.
4. صفحات مستقل AdminGate دست‌نخورده ماندند (دو پوسته — §۱۷)؛ لینک متقابل از طریق sidenav و ایندکس آموزشی موجود برقرار است.

## ۶) وضعیت Dashboard و KPIها

- هر ۸ کارت از `/admin/overview` واقعی می‌آیند؛ **هیچ دادهٔ ساختگی یافت نشد** (کاوش + QA).
- کلیک‌پذیری: کتاب‌ها→books، کاربران→users، درآمد→plans، تنظیمات→integrations از قبل موجود بود؛ در این فاز «مصرف توکن امروز» و «گفت‌وگوها و آزمون‌ها» به **observability** (گزارش واقعی مصرف AI) وصل شدند؛ type prop به‌ترتیب گسترش یافت.
- کارت‌های بدون مقصد معتبر قابل‌کلیک نشدند (طبق محدودیت فاز).

## ۷) عملیات AJAX

- همهٔ mutationهای پنل‌ها بدون reload کامل انجام می‌شوند (کاوش: هیچ `window.location` در مسیرهای ادمین؛ QA: مارکر SPA پس از deactivate→activate کاربر دست‌نخورده ماند).
- `AdminUsersPanel` از `apiClient` با دسته‌بندی خطا (401/403/409/422/428/429/5xx/network)، in-flight de-dup و toast استفاده می‌کند؛ پنل‌های قدیمی‌تر raw fetch + `onUnauthorized` دارند (همگن‌سازی کامل در §۱۷).
- Confirmation برای عملیات حساس در AdminUsersPanel و AdminCatalogManager موجود و حفظ شد (QA: دیالوگ تأیید در toggle فعال‌سازی).

## ۸) Search / Filter / Sort / Pagination

- سمت سرور: users (q/role/status/plan/page)، catalog (q+فیلتر هر فیلد+sort+page)، audit-logs (feature/status/flagged/user/days/offset)، podcast episodes (status)، flashcard decks (source_type/public_only).
- **فاز ۰۶ هر دو سمت را URL-دار کرد:** خواندن هنگام mount + بازتاب با `replaceState` (بدون آلودگی تاریخچه). سنجه‌های واحد (`phase06AdminUrlContract.test.tsx`) + سناریوی QA مرورگر (جست‌وجوی کاربر → reload → بازگشت دقیق نتیجه) هر دو پاس شدند.

## ۹) مجوزها و RBAC

- هیچ مجوزی برای «نمایش دکمه» تغییر نکرد؛ همهٔ مسیرهای ادمین همچنان پشت `require_admin` هستند و تست ساختاری `test_every_admin_operation_carries_require_admin` در اجرای کامل سبز ماند.
- QA مرورگر با context جداگانه اثبات کرد نشست دانش‌آموز روی `GET /admin/users` پاسخ **403** می‌گیرد (کوکی ادمین در آن context حضور نداشت).
- تفکیک مجوزهای موجود حفظ شد: `can_read_users` ≠ `can_assign_role` ≠ `can_manage_education_catalog` ≠ `can_read_audit`؛ reauth (`X-Reauth-Password`) برای تغییر نقش/حذف/رمز.
- مجوزهای جدید اضافه نشد (ضرورت واقعی دیده نشد؛ §۱۷).

## ۱۰) Audit و حفاظت Secrets

- **۱۵ نقطهٔ mutation که قبلاً بدون Audit بودند اکنون `AdminActionLog` می‌نویسند** از طریق ماژول مشترک جدید `app/services/admin_action_log.py` (actor از `request.state.admin_identity`: `admin-console` یا `user:<id>`): کتاب (PATCH/DELETE/reprocess)، provider (create/update/delete)، مسیر مدل (set/delete)، سهمیه (policy/feature set/delete)، billing (settings/plan)، تنظیمات runtime (update/reset).
- **ممنوعیت Secret در payload:** audit فقط نام فیلدها/مقادیر غیرمحرمانه را ثبت می‌کند؛ تست `test_quota_billing_and_settings_are_audited` صراحتاً assert می‌کند مقدار کلید در payload نیست.
- حفاظت موجود Secrets دست‌نخورده ماند: کلیدها Fernet-رمز، serializer فقط `api_key_masked`، تست شسته‌رفتنِ (`sweep`) هر GET ادمین در اجرای کامل سبز.

## ۱۱) فایل‌های تغییرکرده و جدید

| فایل | نقش |
|---|---|
| `backend/app/services/admin_action_log.py` (جدید) | نوشتار مشترک AdminActionLog با actor-resolution |
| `backend/app/api/admin.py` | ۱۵ نقطهٔ mutation → audit؛ امضای handlerها `request: Request` گرفتند (قرارداد API بدون تغییر) |
| `backend/tests/test_phase06_admin_audit.py` (جدید) | ۳ تست: lifecycle کتاب، provider/route بدون secret، quota/billing/settings |
| `frontend/components/AdminSideNav.tsx` | Link واقعی + تب podcasts |
| `frontend/components/AdminPodcastsPanel.tsx` (جدید) | نمای read-only آمار/اپیزود با فیلتر URLدار و empty state صادق |
| `frontend/app/admin/page.tsx` | import + رندر تب podcasts (تنها تغییر) |
| `frontend/components/AdminUsersPanel.tsx` | read-back فیلترها از URL (`readFiltersFromUrl`) |
| `frontend/components/AdminCatalogManager.tsx` | URL contract صفحه/q/sort/direction |
| `frontend/components/AdminObservabilityPanel.tsx` | URL contract شش پارامتر |
| `frontend/components/AdminFlashcardsPanel.tsx` | URL contract source/public |
| `frontend/components/AdminOverviewPanel.tsx` | دو کارت KPI کلیک‌پذیر به observability |
| `frontend/tests/adminNav.test.tsx` | سنجه‌های Link/href/active/education |
| `frontend/tests/phase06AdminUrlContract.test.tsx` (جدید) | ۵ سنجهٔ URL contract + پادکست |

Patch تفاضلیِ فقط-فاز-۰۶: `download/phase06/backup/phase06_changes.patch` (reverse dry-run: OK).

## ۱۲) Migrationهای احتمالی

**هیچ Migration لازم نشد** — `admin_action_logs` از قبل در مدل‌ها و زنجیرهٔ Alembic وجود دارد و تغییرات فقط کد/قرارداد پاسخ هستند.

## ۱۳) نتایج Backend Tests

```text
cd backend && .venv/bin/pytest -q tests
→ 515 passed, 2 skipped  (baseline پیش از فاز: 512 passed, 2 skipped — +3 تست audit؛ صفر failed)
skipها (طبق طراحی opt-in): test_phase4_postgres_smoke, test_podcast_quota_gate
تست‌های جدید: .venv/bin/pytest -q tests/test_phase06_admin_audit.py → 3 passed
تست ساختاری require_admin روی همهٔ مسیرهای ادمین: پاس (در اجرای کامل)
```

## ۱۴) نتایج Frontend Tests

```text
npx vitest run  → 19 فایل / 165 passed  (پیش از فاز: 137+22=159؛ +6 سنجهٔ nav به‌روزشده و +5 سنجهٔ URL/podcasts جدید؛ صفر failed)
npx tsc --noEmit → پاک (exit 0)
npx eslint .    → exit 0
BACKEND_ORIGIN=http://127.0.0.1:8000 npm run build → موفق (production build برای QA)
```

## ۱۵) نتایج Playwright QA (production build، real backend)

`/home/z/.venv/bin/python scripts/qa06/qa_admin.py` → **12/12 PASS** (شواهد: `download/phase06/evidence/browser/` + `qa_log.json`):

| سناریو | نتیجه |
|---|---|
| ورود ادمین با فرم واقعی | PASS |
| داشبورد با ۸ کارت KPI واقعی (`/admin/overview`) | PASS |
| ناوبری با لینک‌های sidenav + Active از URL (`tab=users` + کلاس active) | PASS |
| تب podcasts: empty state صادق روی دادهٔ خالی (بدون عدد ساختگی) | PASS |
| Refresh روی تب → همان تب (URL-driven) | PASS |
| Back/Forward مرورگر بین بخش‌های قبلی/observability | PASS |
| جست‌وجوی کاربر → در URL → **بعد از Reload** فیلتر و نتیجه بازگشت | PASS |
| mutation معکوس‌پذیر (غیرفعال→تأیید→فعال‌سازی) **بدون reload کامل** + حفظ فیلتر | PASS |
| نشست دانش‌آموز روی API ادمین → **403** (context بدون کوکی ادمین) | PASS |
| ابطال نشست ادمین → فرم ورود واقعی (قفل پنل) | PASS |
| خطای hard کنسول = صفر (فقط 404 تصویر فیکسچر QA) | PASS |

## ۱۶) قابلیت‌های قبلی حفظ‌شده

- **Education Catalog:** ۱۴ صفحه و چرخهٔ CRUD/archive/PDF/copy دست‌نخورده؛ فقط URL contract اضافه شد؛ تست‌های `test_admin_catalog_management.py` سبز در اجرای کامل.
- **Users & Auth/RBAC/CSRF:** مسیرها و قراردادها بدون تغییر؛ 21 تست `test_user_auth_admin.py` سبز.
- **Podcast (04B/04C-A):** lifecycle کاربر، quota accounting و player دست‌نخورده؛ فقط نمای read-only ادمین اضافه شد؛ تست‌های podcast سبز.
- **Learning (فاز ۰۵):** فیلترهای بانک اشتباهات، CTAها و mastery بدون تغییر؛ 512→515 فقط با تست‌های جدید.
- فایل‌های تغییرکردهٔ فازهای قبل (working tree) حفظ شدند؛ تنها هم‌پوشانی (`app/admin/page.tsx`) additive بود.

## ۱۷) محدودیت‌ها و موارد PARTIAL (تصمیم با مالک)

1. **Retry ادمینِ پادکست: BACKEND_MISSING** — retry/cancel فقط endpointهای مالک-محور کاربرند (`/api/v1/podcasts/{id}/retry`)؛ endpoint ادمین وجود ندارد و ساخت آن (و منطق سهمیهٔ retry برای کاربر دیگر) از scope فاز خارج بود؛ نمای ادمین read-only ماند.
2. **دو پوستهٔ ادمین:** `/admin` و صفحات AdminGate (education/providers/observability/roles) هنوز دو لاگین/سربر دارند — یکسان‌سازی پوسته refactor بزرگ است و نشد.
3. **تکرار UI کاربران در تب users:** `AdminUsersPanel` + بلوک legacy قدیمی (استفاده از CSV/usage) هر دو رندر می‌شوند؛ حذف legacy حذف قابلیت (export) است و به تصمیم مالک موکول شد.
4. **همگن‌سازی apiClient:** پنل‌های قدیمی‌تر (providers/settings/…) هنوز raw fetch دارند (کار می‌کنند؛ فقط خطای دستی‌تر) — تبدیل کامل تغییر گسترده بود.
5. **فیلتر سروری جدید نساخته شد** برای books/providers/skills/capabilities (دادهٔ کوچک، خطر شلی قرارداد)؛ در صورت رشد داده، اضافه‌کردن `q/page` به `/admin/books` پیشنهاد می‌شود.
6. **Audit upload-and-ingest و فلش‌کارت/مهارت‌ها** اضافه نشد (دامنهٔ فاز: lifecycle/پیکربندی) — زیرساخت مشترک آماده است و هر نقطهٔ جدید یک خط است.
7. **Permissionهای جدید** (مثلاً `can_manage_providers`) اضافه نشد — ضرورت واقعی با تک‌مدیرِ فعلی وجود نداشت؛ تست‌سانی لازم دارد.

## ۱۸) Rollback دقیق و محدود به همین فاز

```bash
cd /home/z/my-project/iran-tutor-main
patch -p1 -R < /home/z/my-project/download/phase06/backup/phase06_changes.patch
```
فقط ۱۴ مسیرِ فاز ۰۶ را برمی‌گرداند (۹ فایل + ۵ فایل جدید شامل گزارش) و به تغییرات فازهای 04B/04C-A/05 آسیب نمی‌زند (dry-run معکوس: OK). هیچ commit/push انجام نشده؛ شاخهٔ پیشنهادی مالک: `redesign/phase06-admin-control-center`.

## ۱۹) چک‌لیست دستی مدیر

1. `/admin` → ورود با رمز ادمین → نمای کلی: ۸ کارت واقعی، دکمهٔ بروزرسانی.
2. کلیک هر کارت: کتاب‌ها→تب کتاب، کاربران→تب کاربران، درآمد→plans، مصرف امروز→observability.
3. sidenav: هر آیتم لینک واقعی است (کلیک راست → «باز کردن در تب جدید» کار می‌کند).
4. تب کاربران → جست‌وجوی شماره → Refresh → جست‌وجو و نتیجه سر جایش‌اند (URL: `?tab=users&q=…`).
5. باز کردن کاربر → «غیرفعال‌سازی» → دیالوگ تأیید → پس از اجرا، جست‌وجو/صفه حفظ می‌شود و صفحه reload نمی‌شود → «فعال‌سازی» برای بازگشت.
6. تب پادکست‌ها: آمار واقعی؛ با دادهٔ خالی پیام صریح «اپیزودی … ثبت نشده است».
7. تب شفافیت: فیلترها (feature/status/days) → Refresh → همان نتیجه؛ صفحه‌بندی offset در URL.
8. `/admin/education/cycles` → صفحه‌بندی/مرتب‌سازی → Refresh → حفظ؛ حذف رکورد وابسته → 409 فارسی + شمارش وابستگی.
9. پنل ارائه‌دهنده‌ها → ساخت provider با کلید → پاسخ فقط `api_key_masked` دارد → Audit در `/admin?tab=deep_learning` بخش logs.
10. خروج/انقضای نشست → قفل پنل و فرم ورود فارسی.

## ۲۰) حکم نهایی

**PARTIAL — ADMIN CORE COMPLETE.** معیارهای Navigation، URL refresh-safe، Dashboard واقعی، AJAX بدون reload، حفظ Context، RBAC سمت سرور (403 واقعی)، Audit معتبر برای mutationهای حساس، عدم افشای Secrets، رگرسیون صفر (515+165 سبز)، و QA مرورگر ۱۲/۱۲ — همه با شواهد اجرا تأیید شدند. موارد §۱۷ (retry ادمین پادکست، یکسان‌سازی پوسته‌ها، حذف UI تکراری کاربران، همگن‌سازی apiClient، فیلتر سروری books، Audit نقاط باقی‌مانده) صریحاً مستندند و هیچ‌کدام داده یا KPI ساختگی ندارند.
