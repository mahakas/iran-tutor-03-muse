# گزارش فاز ۰۱ — پوستهٔ برنامه و معماری اطلاعات

> **تاریخ:** ۲۰۲۶-۱۱-۲۳ · **دامنه:** UI foundation — ناوبری URL-driven برای دانش‌آموز و ادمین، بدون تغییر منطق تجاری/API
> **نتیجه: `PASS`** — همهٔ دروازه‌های خودکار سبز؛ موارد نیازمند QA مرورگری واقعی صریحاً در بند ۶ و ۷ فهرست شده‌اند.
> **هیچ commit/push/merge انجام نشده است؛ تغییرات در working tree برای بازبینی مالک باقی است.** branch پیشنهادی: `redesign/phase-01-shell`

---

## ۱. خلاصهٔ تغییرات و دلیل

**مشکل ورودی:** تب‌های پنل ادمین (`adminTab`) صرفاً state داخلی `useState` بودند — refresh، deep link و back/forward به بخش موردنظر ادمین کار نمی‌کرد. در سمت دانش‌آموز، لینک‌های سایدبار هرگز حالت active نمی‌گرفتند (active فقط برای آیتم ثابت «معلم خصوصی» هاردکد شده بود)، ناوبری در ۹ آیتم تختِ «فضای یادگیری» بدون حوزه‌بندی بود، و drawer موبایل (با وجود scrim موجود) بدون Escape، focus management و scroll lock بود.

**راه‌حل (حداقل-تغییر، حفظ مسیرها):**
1. **ادمین:** تب فعال از پارامتر پایدار `?tab=` خوانده می‌شود (`parseAdminTabParam` با fallback به `books`). تابع `setAdminTab` بدون تغییر نام/امضا به یک تابع URL-writer تبدیل شد (`router.push("/admin?tab=<key>", { scroll: false })`) — بنابراین تمام ۱۵ نقطهٔ فراخوانی موجود (پس از ورود، اکشن‌های سریع، GlobalSearch، پرش به کتاب/کاربر) بدون ویرایش رفتار کردند. `useSearchParams` در قالب یک `Suspense` boundary بسته شد (الگوی رسمی Next). چون navigation با search param از جنس همان صفحه است، کامپوننت remount نمی‌شود → نشست ادمین و داده‌های بارگذاری‌شده حفظ می‌ماند و back/forward بین تب‌ها کار می‌کند بدون refresh.
2. **دانش‌آموز:** سایدبار در شش حوزهٔ مشخص‌شده در پرامپت سازمان یافت: **خانه، معلم من، یادگیری، تمرین، پیشرفت، کتابخانه** — همه روی routeهای واقعی موجود (بدون route/صفحهٔ تکراری). active state از `usePathname()` استخراج می‌شود. حوزهٔ «کتابخانه» به انکرای واقعی `/#today-class` (نوار انتخاب کتاب در صفحهٔ کلاس) می‌رود.
3. **استخراج تدریجی:** بخش ناوبری سایدبار StudentApp به کامپوننت جدید `StudentSideNav` منتقل شد (فقط دامنهٔ shell؛ recent chats، دکمهٔ گفت‌وگوی تازه و AccountMenu عمداً در StudentApp ماندند). هوک مشترک `useNavDrawer` برای هر دو drawer (دانش‌آموز و ادمین) Escape، انتقال فوکوس و scroll lock مشروط به media query فراهم می‌کند.
4. **دسته‌بندی ادمین:** همان `AdminSideNav` موجود به‌روزرسانی شد (نه کپی): ۱۵ tab بدون افزودن/حذف در **۹ دستهٔ** هدف دسته‌بندی شدند (بند ۶: تکلیف دستهٔ دهم).

**نگاشت نهایی ادمین (همه مقصدهای واقعی):**
| دسته | tabها |
|---|---|
| نمای کلی و سلامت | overview |
| برنامه درسی و کتاب | books |
| پردازش دانش | kb، flashcards، deep_learning، rich_study |
| کاربران و دسترسی | users، roles |
| هوش مصنوعی: مدل‌ها و کلیدها | providers، integrations |
| قابلیت‌ها و مهارت‌ها | capabilities، skills |
| مصرف و مالی | plans |
| کیفیت و ممیزی | observability |
| تنظیمات | appearance |

**نگاشت دانش‌آموز:** خانه→`/` · معلم من→معلم خصوصی/جستجوی گفت‌وگو/سطل بازیافت (اکشن‌های همان صفحهٔ `/`) · یادگیری→`/living-book`، `/notebook`، `/podcast` · تمرین→آزمون‌های من (اکشن) + `/flashcards`، `/mistakes`، `/deep-solve` · پیشرفت→`/mastery` · کتابخانه→`/#today-class`. قابلیت-گیتینگ موجود (`capabilityMenuEnabled`) عیناً حفظ شد؛ حوزه‌ای که همهٔ آیتم‌هایش gate شود کلاً رندر نمی‌شود.

## ۲. فایل‌های تغییرکرده/جدید

| فایل | نقش |
|---|---|
| `frontend/lib/useNavDrawer.ts` | **جدید** — primitive مشترک drawer: Escape، focus in/out، قفل اسکرول body فقط در عرض‌های overlay (پارامتر `scrollLockQuery`) |
| `frontend/components/StudentSideNav.tsx` | **جدید** — شش حوزهٔ ناوبری دانش‌آموز، active از URL، gating با capability، بدون state داخلی |
| `frontend/components/AdminSideNav.tsx` | **به‌روزشد** — دسته‌بندی ۹گانه هدف، صادرات `ADMIN_TAB_KEYS`/`ADMIN_DEFAULT_TAB`/`parseAdminTabParam` (قرارداد `?tab=` در یک نقطه)، اتصال هوک drawer |
| `frontend/app/admin/page.tsx` | **به‌روزشد** — `adminTab` از `?tab=` خوانده می‌شود؛ `setAdminTab` = `router.push(scroll:false)`؛ wrapper `Suspense`؛ افزودن `setAdminTab` به deps سه hook (الزام exhaustive-deps) |
| `frontend/components/StudentApp.tsx` | **به‌روزشد** — جایگزینی لیست تخت با `StudentSideNav` (۹۴ خط حذف/انتقال)، هوک drawer + ref دکمهٔ بستن، `id="today-class"` روی نوار کتاب، حذف ۶ آیکون بلااستفاده |
| `frontend/app/globals.css` | **به‌روزشد** — فقط افزودنی: `body.nav-drawer-open{overflow:hidden}`، `#today-class{scroll-margin-top:84px}`، استایل fallback ادمین |
| `frontend/tests/StudentSideNav.test.tsx` | **جدید** — ۸ تست (حوزه‌ها، active از URL، gating، badge فارسی، اکشن‌ها) |
| `frontend/tests/adminNav.test.tsx` | **جدید** — ۷ تست (قرارداد `?tab=`، پوشش یکتای ۱۵ tab، دسته‌ها، Escape) |
| `frontend/tests/useNavDrawer.test.tsx` | **جدید** — ۶ تست (focus، Escape، scroll lock مشروط) |

هیچ فایل بک‌اند، endpoint، schema، route موجود یا وابستگی جدید تغییر نکرده است. دلتای این فاز: ۴ فایل تغییرکرده + ۵ فایل جدید (بقیهٔ ۱۵ورودیِ diff نسبت به آرشیو، متعلق به فازهای ۰۰/۰۰A قبلی است).

## ۳. قابلیت‌های حفظ‌شده و تست محافظ

- **۱۵ تب ادمین بدون افزودن/حذف** — تست «پوشش یکتا» (`adminNav.test.tsx`) تضمین می‌کند هر tab دقیقاً از یک نقطهٔ منو قابل‌دسترس است (نه لینک مرده، نه تکراری).
- **side effectهای data-loading انتخاب تب** (`handleAdminNavSelect`) عیناً حفظ شد؛ لینک عمیق `?tab=overview` هم داده دارد چون `fetchOverviewData` در اثر احراز هویت اجرا می‌شود (خط ۱۰۲۳ صفحهٔ ادمین).
- **sync آدرس AdminUsersPanel** (فاز ۰۰A) سازگار است: از `window.location.search` کامل می‌خواند و پارامتر `tab` را دست نمی‌زند.
- **gating capabilityها و badge فارسی آزمون‌ها** عیناً — تست‌شده در `StudentSideNav.test.tsx`.
- **مسیرهای موجود** (`/flashcards`، `/mistakes`، `/mastery`، `/deep-solve`، `/notebook`، `/living-book`، `/podcast`، `/study/[bookId]`، `/account/*`، `/admin*`) هیچ rename/حذفی نداشتند.
- **رفتارهای قبلی سایدبار** (گفت‌وگوی تازه ⌘K، گفت‌وگوهای اخیر، AccountMenu، لینک پلن‌ها) بدون تغییر مانده‌اند.
- رگرسیون کامل: ۳۹ تست فرانت‌اند موجود + ۴۶۸ تست بک‌اند، همه پاس (بند ۴).

## ۴. فرمان‌های اجراشده و خروجی واقعی

| فرمان | نتیجه |
|---|---|
| `npx tsc --noEmit` | exit 0 |
| `npm test` (vitest) | **۸ فایل / ۶۰ تست: همه پاس** (۶۰ passed, 0 failed — شامل ۲۱ تست جدید) |
| `npm run lint` (eslint .) | exit 0 — صفر خطا/هشدار |
| `npm run build` | exit 0 — `✓ Compiled successfully in 16.4s`، همهٔ routeها ساخته شد |
| `backend/.venv/bin/python -m pytest -q tests` | **۴۶۸ passed، ۱ skipped، ۲ warnings در 195.98s** — exit 0 (مطابق baseline فاز ۰۰A؛ skip همان تست opt-in فاز ۴ است) |

## ۵. تست‌های اجرا‌نشده و دلیل

- **تست smoke فاز ۴ روی PostgreSQL** (`PHASE4_PG_URL`): opt-in است و در این اجرا تنظیم نشد — در بازبینی نهایی فاز ۰۰A روی PostgreSQL واقعی پاس شده و در این فاز هیچ تغییر دیتابیسی وجود ندارد.
- **تست مرورگری واقعی (Playwright/manual)**: sandbox امکان دانلود Chromium را ندارد (محدودیت مستند در `UI_POLISH_REPORT.md`)؛ refresh/back/forward در سطح مرورگر به چک‌لیست بند ۷ موکول شد. پوشش خودکارِ معادل: قرارداد `?tab=` و active-from-URL در vitest تست شده‌اند؛ back/forward تابع رفتار استاندارد `router.push` در Next App Router است.

## ۶. ریسک‌های باقیمانده و تصمیم‌های نیازمند مالک

1. **دستهٔ «صف کارها/سلامت» از پرامپت فاز، tab اختصاصی ندارد** (تصمیم مالک): سلامت سرویس‌ها در «نمای کلی»، صف پردازش کتاب در «پردازش دانش» و صف بازبینی پرچم‌ها در «کیفیت و ممیزی» پوشش داده می‌شوند. ساخت tab/panel جدید مستلزم endpoint جدید بود و از scope (و ممنوعیت‌های) فاز خارج؛ اگر مالک tab مستقل بخواهد، در فاز بعدی با backend لازم پیاده شود.
2. **دو تغییر ریز UI عامدانه**: (الف) دات هاردکد «معلم خصوصی» حذف شد — حالت active روی `/` حالا توسط آیتم «کلاس درس» نشان داده می‌شود (یک آیتم فعال به‌جای دو تظاهر متناقض)؛ (ب) اکشن‌های آزمون/جستجو/سطل drawer را می‌بندند (در موبایل ضروری بود؛ قبلاً drawer باز می‌ماند).
3. **پاک‌شدن query params زیرتب‌ها هنگام پرش بین تب‌های ادمین**: پرش از users به plans با `router.push('/admin?tab=plans')` فیلترهای URL مربوط به users را پاک می‌کند (رفتار قبلی: params در URL می‌ماندند ولی تب دیگر از آنها استفاده نمی‌کرد). بازگشت به users با فیلترهای پیش‌فرض شروع می‌شود.
4. **fallback چشمک `Suspense`** روی لینک عمیق ادمین (یک فریم؛ قابل‌قبول برای پنل مدیریتی).
5. **QA مرورگری واقعی** (RTL، تم تاریک، responsive 360/768/1024، KaTeX) انجام نشده — بند ۷.
6. **Rollback:** `git checkout -- frontend/app/admin/page.tsx frontend/components/StudentApp.tsx frontend/components/AdminSideNav.tsx frontend/app/globals.css && rm frontend/lib/useNavDrawer.ts frontend/components/StudentSideNav.tsx frontend/tests/{StudentSideNav,adminNav,useNavDrawer}.test.tsx` (بدون commit، فقط working tree).

## ۷. چک‌لیست تست دستی فارسی

**ادمین (`/admin`):**
- [ ] `admin / 123` وارد شود؛ URL بدون `?tab=` → تب پیش‌فرض «کتاب‌ها».
- [ ] `/admin?tab=users` مستقیم باز شود (تب جدید) → پس از ورود، مستقیم «کاربران» باز شود؛ F5 همان تب بماند.
- [ ] کلیک چند تب → Back/Forward مرورگر بین تب‌ها جابه‌جا شود و صفحه refresh نشود؛ اسکرول صفحه نپرد.
- [ ] منوی ۹دسته‌ای سمت راست؛ هر آیتم یک‌بار active شود؛ در ≤1024px دکمهٔ منو → drawer با scrim؛ Escape و کلیک روی scrim ببندد؛ فوکوس به دکمهٔ بستن برود و پس از بستن برگردد.
- [ ] پرش‌های GlobalSearch ادمین (کتاب/کاربر/پلن) URL را با `?tab=` هماهنگ کنند.

**دانش‌آموز (`/`):**
- [ ] سایدبار شش حوزه: خانه، معلم من، یادگیری، تمرین، پیشرفت، کتابخانه.
- [ ] `/flashcards` → «فلش‌کارت‌ها» bold و highlight؛ Back → «کلاس درس» highlight.
- [ ] «کتاب‌های درسی» → نوار «کلاس امروزت» (اسکرول نرم، زیر topbar).
- [ ] تعویض پایه/شاخه/رشته → لیست حوزه‌ها بدون پرش یا refresh به‌روز شود.
- [ ] موبایل 360px: hamburger → drawer؛ Escape/scrim بستن؛ قفل اسکرول پس‌زمینه؛ پس از انتخاب فصل، drawer بسته شود.
- [ ] capability خاموش در ادمین → آیتم مربوط از سایدبار حذف و حوزهٔ خالی برداشته شود.
- [ ] تم تاریک و `prefers-reduced-motion`: بدون رگرسیون بصری.

**APIهای درگیر (بدون تغییر):** همهٔ فراخوانی‌های قبلی همان‌اند؛ فاز صرفاً UI/navigations است.

## ۸. نتیجه

معیارهای فاز: نگاشت واقعی و بدون تکرار برای ۶ حوزهٔ دانش‌آموز و دسته‌بندی ادمین ✓ (تست پوشش یکتا) · URL-driven بودن تب ادمین و active state از URL ✓ (تست قرارداد `?tab=`) · refresh/deep link/back-forward بدون از دست رفتن نشست ✓ (معماری search-param + build موفق) · drawer موبایل با Escape/focus/scrim/scroll-lock ✓ (تست هوک) · حفظ همهٔ قابلیت‌ها و تست‌های قبلی ✓ (۶۰/۶۰ و ۴۶۸/۱) · بدون تغییر endpoint/route/وابستگی ✓ (diff بند ۲). دو تفاوت UI ریز و تکلیف دستهٔ دهم در بند ۶ شفاف مستند شده‌اند.

**`PASS`**
