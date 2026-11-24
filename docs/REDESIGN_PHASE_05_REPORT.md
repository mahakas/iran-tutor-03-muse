# REDESIGN — گزارش فاز ۰۵: یکپارچه‌سازی تمرین، حل عمیق، اشتباهات و تسلط

> **تاریخ:** ۲۰۲۶-۱۱-۲۴ · **شاخه:** `main` (بدون commit؛ همهٔ تغییرات در working tree) · **پایه:** `7db4f35`
> **وضعیت نهایی: PASS — همهٔ معیارهای پذیرش فاز با شواهد اجرای واقعی اثبات شده‌اند.**

## ۱) خلاصهٔ تغییرات و دلیل

کاوش اولیهٔ فاز (کد + تست، نه مستندات) نشان داد سه ستون اصلی از قبل سالم‌اند: Deep Solve کاملاً از `available_actions` سرور پیروی می‌کند، آزمون کلید را پیش از submit افشا نمی‌کند و mastery فقط با شواهد واقعی محاسبه می‌شود. شکاف واقعی، **عدم اتصال این حلقه‌ها به هم** بود: کارنامهٔ آزمون هیچ خروجی‌ای به بانک اشتباهات/منبع کتاب/مسیر تسلط نداشت، کارت اشتباه به منبع کتاب لینک نمی‌شد، فیلتر بانک اشتباهات فقط `status` بود (در حالی که داده‌ها `book_id`/`chapter_number`/`error_tag` دارند) و «گام بعدی» در mastery وجود نداشت. بنابراین تغییرات این فاز حداقلی و فقط اتصال‌دهنده است:

1. **فیلترهای سمت سرور بانک اشتباهات** — `GET /api/v1/mistakes` و `GET /api/v1/mistakes/practice-set` اکنون پارامترهای اختیاری `book_id`، `chapter_number` و `error_tag` را می‌پذیرند (اعتبارسنجی `error_tag ∈ {wrong, skipped}` با 422). شمارنده‌های وضعیت (`counts`) درون همان فیلترِ دامنه محاسبه می‌شوند تا چیپ‌های وضعیت در نمای فیلترشده معنادار بمانند. بدون پارامتر، رفتار دقیقاً مانند قبل است (backward-compatible).
2. **CTAهای کارنامهٔ آزمون** — پس از submit، کارنامه سه مسیر می‌دهد: «مرور اشتباهات در بانک اشتباهات» (`/mistakes`، فقط وقتی غلط/بی‌پاسخ > 0)، «تمرین دوباره» (باز کردن مودال آزمون جدید از طریق `onStartNewExam` اختیاری)، «منبع کتاب» (`/study/{book_id}`) و «شواهد تسلط» (`/mastery`).
3. **اتصال کارت اشتباه** — هر کارت لینک «منبع در کتاب» → `/study/{book_id}` و پس از تبدیل به فلش‌کارت، لینک «مشاهدهٔ فلش‌کارت‌ها» → `/flashcards` می‌گیرد؛ UI فیلتر (انتخابگر کتاب رسمی + فصل + نوع خطا + وضعیت مرور) درخواست‌ها را سمت سرور فیلتر می‌کند و «پاک‌کردن فیلترها» هم دارد.
4. **پیشنهاد گام بعدی deterministic در mastery** — تابع خالص `nextChapterStep` در `lib/phase5.ts` فقط از دادهٔ سرور (وضعیت، امتیاز، شمارنده‌های شواهد exam/solve/flash) اولویت ثابتِ «آزمون → حل گام‌به‌گام → فلش‌کارت → مرور اشتباهات» را با متن دلیلِ قابل‌فهم پیشنهاد می‌دهد؛ بدون AI، بدون عدد ساختگی و برای فصل قفل/مسلط `null`.
5. **CTA اتمام Deep Solve** — پس از رسیدن به پاسخ نهایی: «منبع در کتاب»، «مسئلهٔ تازه» و ارجاع به `/mastery`.
6. **سخت‌سازی کلید در کلاینت** — فیلد بلااستفادهٔ `correct_option` از type `MistakeItem` حذف شد تا رندر تصادفی کلید در حالت فهرست ناممکن شود؛ و radioهای تمرین از radioهای فهرست جدا شدند (`mistake-practice-{id}`) تا تلاقی گروه radio در یک صفحه از بین برود.

هیچ الگوریتم mastery، منطق SM-2، سهمیه، مجوز یا مسیر LLM تغییر نکرد. هیچ migration جدید لازم نشد (تغییرات فقط query هستند).

## ۲) فایل‌های تغییرکرده/جدید و نقش هر فایل

| فایل | نقش |
|---|---|
| `backend/app/services/mistake_bank_service.py` | فیلترهای دامنه (`_apply_scope_filters`) در `list_items` و `practice_set`؛ شمارنده‌های scoped؛ اعتبارسنجی `error_tag` |
| `backend/app/api/phase5.py` | پارامترهای query اختیاری روی دو endpoint بانک اشتباهات |
| `backend/tests/test_phase5_deep_learning.py` | دو تست جدید: فیلترها + شمارنده‌های scoped + practice-set فیلترشده؛ مالکیت اشتباه (404 برای کاربر دیگر + دست‌نخوردگی ردیف) |
| `frontend/lib/phase5.ts` | `MistakeErrorTag`، برچسب‌ها، `mistakeFilterQuery`، `MasteryComponentEvidence`، تابع خالص `nextChapterStep`؛ حذف `correct_option` از `MistakeItem` |
| `frontend/components/MistakeBankWorkspace.tsx` | فیلترهای کتاب/فصل/نوع خطا/وضعیت با اعمال سمت سرور، لینک منبع کتاب، لینک فلش‌کارت‌ها، پاک‌کردن فیلترها، radio جدای تمرین |
| `frontend/components/ExamRunner.tsx` | ردیف CTA کارنامه (`onStartNewExam` اختیاری + لینک‌های mistakes/mastery/study) |
| `frontend/components/StudentApp.tsx` | پاس‌دادن `onStartNewExam` به ExamRunner (پاک‌کردن آزمون فعال + باز کردن مودال آزمون جدید) |
| `frontend/components/DeepSolveWorkspace.tsx` | CTAهای اتمام جلسه |
| `frontend/components/MasteryWorkspace.tsx` | نمایش «گام بعدی» deterministic زیر هر فصل |
| `frontend/tests/phase5NextStep.test.ts` (جدید) | ۱۰ سنجهٔ واحد توابع خالص (قواعد اولویت، حالت‌های مرزی، سریال‌سازی query) |
| `frontend/tests/MistakeBankWorkspace.test.tsx` (جدید) | ۵ سنجه: شمارنده‌های scoped و عدم افشای کلید در فهرست، فیلترهای سروری فصل/خطا/کتاب، reset، تمرین با دامنه، ثبت پاسخ، لینک‌های منبع/فلش‌کارت |
| `frontend/tests/ExamRunner.test.tsx` (جدید) | ۴ سنجه: کلید در DOM پیش از submit نیست + submit با پاسخ‌های انتخابی، submit خودکار آزمون منقضی دقیقاً یک‌بار، CTAهای کارنامه، پنهان‌شدن CTA مرور در کارنامهٔ بی‌نقص |
| `frontend/tests/DeepSolveWorkspace.test.tsx` (جدید) | ۳ سنجه: فقط اکشن‌های مجاز سرور، CTAهای اتمام، عدم رندر محتوای گام‌های pending |

بستهٔ patch تفاضلیِ فقط-فاز-۵: `download/phase05/backup/phase05_changes.patch` (۱۳ فایل، ۱٬۱۰۳ خط؛ dry-run اعمال معکوس: OK).

## ۳) قابلیت‌های حفظ‌شده و تست محافظ آن‌ها

- **Deep Solve مطابق سرور:** `test_deep_solve_ladder_hides_answer_until_full_and_records_mastery` و تست‌های 502/orphan قبلی سبز ماندند؛ تست جدید UI اثبات می‌کند دکمه‌ها فقط از `available_actions` می‌آیند.
- **عدم افشای کلید آزمون:** `test_exams.py::public_exam` و `test_mistake_practice_lifecycle` قبلی + دو سنجهٔ جدید (backend و frontend) — کلید فقط در پاسخ submit/کارنامه.
- **مالکیت/IDOR:** `get_owned` برای deep-solve و `_owned` اشتباهات؛ تست جدید مالکیت (404 + عدم تغییر ردیف کاربر دیگر).
- **mastery بدون دادهٔ ساختگی:** `test_mastery_score_weighting_threshold_and_unlock` و نگاشت صفحه→هدف قبلی سبز ماندند؛ QA مرورگر اثبات می‌کند چیپ «گام بعدی» فقط از شواهد واقعی می‌آید (با شواهد آزمون، چیپ آزمون نمایش داده نمی‌شود و چیپ حل گام‌به‌گام لینک `/deep-solve` دارد).
- **قانون انتشار خودکار کتاب و فیلتر صفحات RAG** دست‌نخورده (تست‌های `test_phase10_auto_publish` در اجرای کامل سبز).
- **مسیرهای 04B/04C (پادکست):** ۱۱ فایل پیش‌تر تغییرکردهٔ 04C-A در working tree دست‌نخورده ماند؛ فقط ۹ فایل مشترک نبود — `StudentApp.tsx` تنها فایل مشترک است و تغییر آن افزودن یک prop اختیاری است (تست‌های PodcastWorkspace/PodcastPlayerPersistence در اجرای کامل سبز).
- **قابلیت‌ها/سهمیه/audit:** همهٔ مسیرهای AI از `capability_runtime`/`ai_gateway` می‌گذرند (`test_phase5_ai_calls_route_through_runtime_and_gateway` سبز).

## ۴) فرمان‌های اجراشده و خروجی واقعی

| فرمان | نتیجهٔ واقعی |
|---|---|
| Baseline: `.venv/bin/pytest -q tests/test_phase5_deep_learning.py tests/test_phase6_rich_study.py tests/test_exams.py tests/test_security_scope_hardening.py` | **100 passed** (۳۹.۹s) |
| Baseline: `npx tsc --noEmit` · `npx vitest run` | پاک · **137 passed** |
| نهایی: `.venv/bin/pytest -q tests` (کل backend) | **512 passed, 2 skipped** (~۲۴۰s)؛ skipها: `test_phase4_postgres_smoke` و `test_podcast_quota_gate` (opt-in با متغیر PG، طبق طراحی) |
| نهایی: `npx vitest run` | **18 فایل / 159 passed** (۱۳۷ قبلی + ۲۲ جدید) |
| نهایی: `npx tsc --noEmit` · `npx eslint components lib tests app` | exit 0 · exit 0 (بدون خطای جدید) |
| `npm run build` (برای QA مرورگر، `BACKEND_ORIGIN=http://127.0.0.1:8000`) | موفق؛ `next start -p 3100` HTTP 200 |
| QA مرورگر (Playwright، real backend + fake provider فقط برای پاسخ LLM): `/home/z/.venv/bin/python scripts/qa05/qa_browser.py` | **20/20 PASS** — ثبت‌نام/ورود واقعی با OTP، گیت پروفایل تحصیلی، آزمون (تایمر، پاسخ، submit، کارنامه)، CTAها، بانک اشتباهات (فیلتر error_tag: ۱۰→۵؛ درخواست `book_id` سمت سرور)، ناوبری `/study/1`، تمرین و تصحیح سروری، نردبان deep-solve تا پاسخ نهایی، تایم‌لاین mastery و چیپ deterministic، صفر خطای hard کنسول |
| سنجه‌های pytest جدید | `pytest -k "filters_scoped or private_to_their_owner"` → **2 passed** |

**شواهد:** `download/phase05/evidence/browser/` (۱۴ اسکرین‌شات) + `qa_log.json` + `download/phase05/logs/` (لاگ‌های کامل pytest/vitest/tsc/eslint/build).

## ۵) تست‌های اجرا‌نشده و دلیل

- **مدل/پردازش واقعی:** QA مرورگر برای پاسخ‌های LLM از fake provider سازگار با OpenAI (`scripts/qa05/fake_provider.py`) استفاده کرد (مسیرهای تولید سؤال، Validator Gate و plan حل). کیفیت محتوای واقعی مدل خارج از فازهای بازطراحی است و قبلاً در ماتریس وضعیت ثبت شده. هیچ ادعایی دربارهٔ کیفیت سؤال/حل با مدل واقعی نمی‌شود.
- **PostgreSQL برای کد جدید فاز ۵:** دو تست جدید روی SQLite اجرا شدند (فیلترها با `select().where()` خنثای dialect هستند و schema جدیدی ندارند). سرور PG اختصاصی QA در این فاز بالا نیامد؛ `test_phase4_postgres_smoke`/`test_podcast_quota_gate` طبق طراحی skip ماندند. اگر مالک بخواهد، اجرای opt-in با `PHASE4_PG_URL` تکرارشدنی است.
- **Redis واقعی، SMS واقعی، دستگاه فیزیکی:** همان محدودیت‌های ثبت‌شدهٔ فازهای قبل؛ در این فاز تغییر نکردند.

## ۶) ریسک‌های باقیمانده، تصمیم‌های مالک، rollback

- **شمارنده‌های فیلترشده:** `counts` حالا درون فیلتر دامنه محاسبه می‌شود؛ اگر مالک ترجیح دهد شمارنده‌ها همیشه کل بانک را نشان دهند، تغییر یک‌خطی در `list_items` است.
- **چیپ «آزمون کوتاه بساز»** به `/?action=new-exam` می‌رود و مودال آزمون جدید را باز می‌کند؛ اتصال خودکارِ کتابِ فصلِ انتخابی به مودال، نیاز به تغییر StudentApp داشت و از scope خارج شد (تصمیم مالک).
- **فقط تولیدکنندهٔ اشتباه، submit آزمون است** (رفتار قبلی): اشتباهات چت/فلش‌کارت ثبت نمی‌شوند — گسترش آن تغییر رفتاری است و به تصمیم مالک نیاز دارد.
- **404 تصویر صفحه در QA** فیکسچری است (no real page images) و خطای محصول نیست.
- **Rollback:** همهٔ تغییرات uncommitted هستند. برای بازگردانی فقط فاز ۵: `cd iran-tutor-main && patch -p1 -R < ../download/phase05/backup/phase05_changes.patch` (بدون آسیب به تغییرات 04B/04C). برای بازگردانی کامل تا پایه: تصمیم با مالک (فایل‌های مشترک با 04C-A).
- **Git:** هیچ commit/push انجام نشد؛ شاخهٔ پیشنهادی برای بازبینی مالک: `redesign/phase05-study-loop`.

## ۷) چک‌لیست تست دستی فارسی (مسیرهای UI/API)

1. `/` → ورود دانش‌آموز → تکمیل کارت پروفایل تحصیلی (پایهٔ ۱۰، نظری، ریاضی‌فیزیک) → انتخاب کتاب در «کلاس امروزت».
2. سایدبار «آزمون‌های من» → «آزمون جدید» → ۳ سؤال / ۵ دقیقه → شروع → تایمر سرور، برچسب «پاسخ‌ها تا پایان آزمون پنهان‌اند».
3. یک سؤال را درست، یکی را غلط پاس بده، آخری را بی‌پاسخ بگذار → «ثبت و دریافت کارنامه» → کارنامه با کلید/توضیح/منبع + چهار CTA.
4. «مرور اشتباهات در بانک اشتباهات» → `/mistakes`: فقط غلط‌ها و بی‌پاسخ‌ها؛ چیپ «بی‌پاسخ» فقط موارد skipped؛ انتخابگر کتاب + فصل + «پاک‌کردن فیلترها».
5. «منبع در کتاب» → `/study/{bookId}` (خوانندهٔ عمیق همان کتاب) → بازگشت → «تمرین دوباره» → پاسخ درست → «درست بود.» + تغییر وضعیت به «در حال تمرین».
6. «ارسال به فلش‌کارت‌ها» → پیام موفقیت + لینک «مشاهدهٔ فلش‌کارت‌ها» → `/flashcards`.
7. `/deep-solve` → مسئلهٔ چندمرحله‌ای + کتاب → نردبان «راهنمای ۱ → راهنمای ۲ → نمایش گام → پاسخ کامل» → پس از پاسخ نهایی: «منبع در کتاب»، «مسئلهٔ تازه»، ارجاع به مسیر تسلط.
8. `/mastery` → همان کتاب → تایم‌لاین فصل‌ها؛ فصل دارای شواهد آزمون باید چیپ «حل گام‌به‌گام یک مسئله» را نشان دهد (نه «آزمون کوتاه بساز») — پیشنهاد deterministic از شواهد.
9. API (curl با نشست دانش‌آموز): `GET /api/v1/mistakes?chapter_number=2&error_tag=skipped` → فقط موارد مطابق؛ `?error_tag=bogus` → 422؛ `GET /api/v1/mistakes` بدون فیلتر → پاسخ بدون `correct_option`.

## ۸) نتیجهٔ نهایی

**PASS — فاز ۰۵ بسته شد.** معیارهای پذیرش: (۱) مسیر کامل تمرین → بازخورد → ثبت اشتباه → مرور → شواهد تسلط با CTAهای واقعی در UI و اثبات مرورگری ۲۰/۲۰؛ (۲) سرور منبع حقیقتِ وضعیت و کلید پاسخ باقی ماند (تست‌های قبلی + ۶ سنجهٔ جدید backend/frontend + سنجهٔ QA)؛ (۳) هیچ دادهٔ ساختگی در KPI و mastery (تابع پیشنهاد فقط از شواهد سرور؛ سنجهٔ QA چیپ را با نبودِ چیپ آزمون وقتی شواهد موجود است، قفل کرد). فاز بعدی طبق قاعده شروع نشد.
