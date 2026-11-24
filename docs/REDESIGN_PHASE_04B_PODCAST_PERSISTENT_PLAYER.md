# Phase 04B — پخش پایدار پادکست و یکپارچگی MediaSession (گزارش نهایی راستی‌آزمایی‌شده)

> تاریخ: ۲۰۲۶-۱۱-۲۴ · شاخهٔ کاری: working tree بدون commit/push (طبق محدودیت فاز)
> ## حکم نهایی: `PASS — VERIFIED IN THIS SESSION`
> همهٔ گزاره‌های این گزارش در همین نشست از صفر اجرا و راستی‌آزمایی شد: ۱۳۲ تست فرانت‌اند، typecheck/lint، production build، و QA مرورگر واقعی (Playwright/Chromium) روی build تولیدی با بک‌اند واقعی و خط لولهٔ واقعی تولید پادکست. هیچ «PASS فرضی» در این گزارش وجود ندارد؛ هر موردِ غیرقابل اثبات در محیط آزمایش به‌صورت صریح PARTIAL ثبت شده است.

---

## ۰) خلاصهٔ اجرا (Audit → پیاده‌سازی → راستی‌آزمایی)

۱. **Audit:** وضعیت موجود مستند شد (بخش ۱). اسنپ‌شات ورودی از قبل شامل پیاده‌سازی اولیهٔ Phase 04B بود؛ این نشست آن را «کاندیدای تأیید» تلقی کرد و کل زنجیرهٔ اثبات را از نو اجرا کرد.
۲. **راستی‌آزمایی آزمایشگاهی:** `vitest run` → **۱۳۲ passed (14 فایل)**، `tsc --noEmit` پاک، `eslint .` پاک، `next build` موفق.
۳. **QA مرورگر واقعی:** سناریوی کامل spec روی build تولیدی اجرا شد → **۱۶/۱۶ گام PASS** با شواهد عکس/JSON/عملیات واقعی localStorage (بخش ۶).
۴. **یافته و اصلاح در همین نشست:** یک وضعیت مرزی واقعی مرورگر (`pause → ended` هنگام رسیدن با seek به پایان) می‌توانست رکورد «تمام‌شده» را دوباره بنویسد. اصلاح شد + ۲ تست رگرسیون اضافه شد (بخش ۷).
۵. **باز-راستی‌آزمایی پس از اصلاح:** تست‌ها/بیلد/QA کامل دوباره سبز شد (همان اعداد همین گزارش).

## ۱) معماری قبل و بعد

**قبل (Audit):**
- `PodcastPlayerProvider` در ریشهٔ برنامه (`frontend/app/layout.tsx` — داخل `AppProvider` و دور `children` + `ToastHost`) یک audio element سراسری (نه در DOM) با `new Audio()` می‌سازد؛ API عمومی: `load/toggle/seek/skip/setSpeed/setVolume/close`.
- بارگذاری صوت فقط از `PodcastWorkspace.playEpisode`: `authFetch(/api/v1/podcasts/{id}/audio)` → Blob → `URL.createObjectURL` → `player.load(track)`. Blob URL پس از reload مرده است.
- هویت/نشست: `useAppContext()` → `user.id`، `authFetch`؛ احراز هویت کوکی‌محور + CSRF (بک‌اند: `require_student` + مالکیت اکید اپیزود؛ صوت فقط از endpoint احراز هویت‌شده با پشتیبانی Range سرو می‌شود).
- الگوی ذخیره‌سازی موجود پروژه: `localStorage` در `lib/preferences.ts`.

**بعد (خلاصهٔ معماری نهایی):**
- `frontend/lib/podcastPlaybackStore.ts` — ذخیرهٔ نسخه‌دار و user-scoped: کلید `darsyar:podcast:playback:v1:{user_id}` (شناسه با `[^a-zA-Z0-9_-]` پاک‌سازی و تا ۶۴ نویسه محدود). فقط فیلدهای غیرحساس: `episodeId, position, speed, wasPlaying, updatedAt`. **هیچ توکن/کوکی/URL امضاشده/blob ذخیره نمی‌شود.** انتخاب localStorage به‌جای IndexedDB به‌دلیل سازگاری با الگوی موجود (`preferences`) و حجم ناچیز رکورد.
- Provider: ذخیرهٔ throttle دار (۵ ثانیه در `timeupdate`) + ذخیرهٔ اجباری در `pause`/`seek`/تغییر سرعت/`pagehide`/`visibilitychange(hidden)`؛ `ended` و بستن پلیر رکورد را پاک می‌کنند.
- Restore پس از reload: با شناسایی `user.id` و در نبود پخش جاری؛ `GET /api/v1/podcasts/{id}` → در 401/403/404 پاک‌سازی امن؛ اگر `status !== "completed"` یا `has_audio=false` → toast «فایل صوتی هنوز آماده نیست» و **رکورد حفظ می‌شود**؛ سپس صوت از همان endpoint احراز هویت‌شده دوباره گرفته می‌شود؛ پس از `loadedmetadata` موقعیت با `min(saved, realDuration)` اعمال و سرعت قبلی (فقط از لیست مجاز ۰٫۷۵ تا ۲) بازیابی می‌شود؛ اگر `saved.position ≥ duration − 1` اپیزود «عملاً تمام‌شده» است: رکورد پاک، شروع از صفر و بنر ادامه حذف می‌شود.
- UI: پلیر کوچک پایین صفحه (`.pc-mini`، RTL) + بنر «ادامهٔ پخش از موقعیت قبلی» با «ادامه» و «از ابتدا» (`.pc-restore*` در `globals.css`). «از ابتدا» رکورد را پاک می‌کند. Autoplay پس از restore عمداً انجام نمی‌شود (سیاست واقعی مرورگرها)؛ کاربر با «ادامه» ادامه می‌دهد.
- MediaSession: یک `useEffect` با `[]` برای lifetime صفحه فقط یک‌بار `play/pause/seekbackward/seekforward/seekto` را ثبت می‌کند (پاک‌سازی با `null` در unmount)؛ همه به همان audio element سراسری متصل‌اند. `previoustrack/nexttrack` عمداً ثبت نشدند — مفهوم واقعی قسمت قبل/بعد وجود ندارد. `metadata` (title/artist/album؛ artwork فقط با URL معتبر `https?/data:image`) در تغییر track، `playbackState` (none/paused/playing) پس از هر تغییر واقعی، و `setPositionState` با duration واقعی و playbackRate صحیح. همهٔ مسیرها با `'mediaSession' in navigator` و try/catch محافظت شده‌اند.
- تغییر حساب/خروج: گذار واقعی A→B یا A→خروج، رکورد حساب قبلی را پاک و پخش را متوقف می‌کند؛ گذار mount/login (null→A) هیچ‌چیز را پاک نمی‌کند (بدون این تفکیک، restore پس از هر refresh می‌شکست — باگ واقعی که در QA مرورگرِ فاز کشف و با تست رگرسیون «user arrives after mount» قفل شده است).

## ۲) فایل‌های تغییرکرده (نسبت به اسنپ‌شات ورودی؛ هر دو در working tree)

| فایل | تغییر | وضعیت |
|---|---|---|
| `frontend/components/PodcastPlayerProvider.tsx` | نگهبان (guard) در `pause` هنگام `element.ended` (جلوگیری از بازنویسی رکورد تمام‌شده) + پنهان‌کردن بنر ادامه برای اپیزود عملاً تمام‌شده در restore | اصلاح این نشست (بخش ۷) |
| `frontend/tests/PodcastPlayerPersistence.test.tsx` | ۲ تست رگرسیون جدید: «pause بعد از ended رکورد را پاک نگه می‌دارد» و «موقعیت ذخیره‌شده در پایان فایل = تمام‌شده: پاک‌سازی و شروع از صفر» | اصلاح این نشست |
| `docs/REDESIGN_PHASE_04B_PODCAST_PERSISTENT_PLAYER.md` | همین گزارش — بازنویسی به نسخهٔ راستی‌آزمایی‌شدهٔ این نشست | گزارش |
| `frontend/lib/podcastPlaybackStore.ts` · `frontend/app/globals.css` · بنر `.pc-restore*` | لایهٔ ذخیرهٔ user-scoped و استایل بنر — بازبینی و تأیید شد؛ در این نشست تغییر نکردند | از اسنپ‌شات (تأییدشده) |
| Backend / Worker / Job lifecycle / Migration | **دست نخورده** — `git status` فقط سه فایل بالا را نشان می‌دهد | — |

## ۳) جزئیات ذخیره‌سازی و بازیابی

- **کلید:** `darsyar:podcast:playback:v1:{user_id}` — دو حساب هرگز کلید مشترک ندارند؛ بازیابی فقط از کلید کاربر جاری خوانده می‌شود.
- **نوشتن:** در `timeupdate` حداکثر هر ۵ ثانیه؛ در `pause` (غیر-`ended`)، `seek`، تغییر سرعت، `pagehide` و `visibilitychange(hidden)` اجباری. `wasPlaying` واقعی لحظهٔ نوشتن ثبت می‌شود.
- **خواندن/اعتبارسنجی:** JSON خراب یا شکل نامعتبر (episodeId غیرصحیح، position نامتناهی/منفی، سرعت خارج از لیست مجاز) → رکورد حذف و بازیابی امن رد می‌شود.
- **بازیابی:** بعد از `loadedmetadata` با کلمپ به duration واقعی؛ موقعیت نزدیک پایان = تمام‌شده → پاک‌سازی + شروع از صفر + بدون بنر.
- **پاک‌سازی:** پایان اپیزود → پاک؛ «از ابتدا» → پاک؛ بستن پلیر → پاک (بی‌میلی صریح کاربر — تصمیم مستند).
- **امنیت:** بدون توکن/کوکی/URL امضاشده/blob در localStorage؛ جداسازی کامل با کلید نسخه‌دار per-user؛ تغییر حساب رکورد حساب قبلی را پاک می‌کند.

## ۴) نحوهٔ اتصال MediaSession

- ثبت یک‌بارهٔ ۵ action handler برای lifetime صفحه — rerender ها handler جدید ثبت نمی‌کنند (تست اختصاصی: تعداد ثبت‌ها پس از دو rerender = ۰).
- `seekbackward/seekforward` پیش‌فرض ۱۵ ثانیه؛ `seekto` از `details.seekTime` مرورگر.
- `metadata` در تغییر track؛ `playbackState` در تغییر `current/isPlaying`؛ `setPositionState` بعد از `loadedmetadata`، seek/skip، تغییر سرعت و play/pause با duration واقعی، position کلمپ‌شده و playbackRate فعلی (>0 وگرنه ۱).
- همهٔ handlerها به `audioRef.current` سراسری وصل‌اند — در QA واقعی دقیقاً یک audio element وجود دارد (تست: `el === audioInstances[0]`).

## ۵) نتایج تمام تست‌ها (اجراشده در همین نشست)

| فرمان | نتیجه |
|---|---|
| `npx vitest run` | **132 passed / 14 فایل** — ۱۰۹ قبلی دست‌نخورده + ۲۱ تست Phase 04B + ۲ تست رگرسیون جدید این نشست |
| `npx tsc --noEmit` | پاک |
| `npx eslint .` | پاک |
| `npm run build` (production) | موفق — `/podcast` در خروجی |
| `pytest -q` (بک‌اند، بدون `.env` محیط QA) | **509 passed / 1 skipped** — یک شکستِ موقت در اجرای اول (`test_settings_read_environment_alias`) فقط برخورد `.env` محیط QA با تست تنظیمات بود و بدون `.env` سبز شد؛ بک‌اند در این فاز تغییری نکرده است |
| Migration جدید | **ساخته نشد** — هیچ نیاز فنی مستند نداشت |

پوشش تست‌های اجباری spec: ذخیره در پخش (throttle ۵ ثانیه) و هنگام pause؛ بازیابی پس از reload (اپیزود/موقعیت/UI/زمان)؛ بازیابی سرعت؛ «از ابتدا» و پاک‌سازی رکورد؛ پاک‌سازی پس از پایان؛ عدم بازیابی برای کاربر دیگر؛ اپیزود حذف/غیرمجاز (404 → پاک امن)؛ metadata نامعتبر (JSON خراب + شکل غلط)؛ شکست دریافت صوت (رکورد حفظ + toast)؛ ورود کاربر بعد از mount؛ بستن پلیر؛ ثبت metadata (بدون artwork / با https / رد `javascript:`)؛ play/pause روی همان element؛ seekbackward/seekforward (۱۵ ثانیه)؛ seekto؛ playbackState پس از هر تغییر واقعی؛ positionState با duration واقعی؛ مرورگر بدون MediaSession؛ عدم ثبت تکراری handler؛ تغییر حساب؛ + ۲ رگرسیون جدید (بخش ۷).

## ۶) QA واقعی مرورگر (Playwright/Chromium headless، production build، همین نشست)

**۶-الف) محیط (با افشای کامل):**
- فرانت‌اند: `next start :3100` روی **production build** همان کد؛ `/api/*` با rewrite همین build به بک‌اند می‌رود.
- بک‌اند: `uvicorn app.main:app :8000` — کد واقعی بک‌اند، دیتابیس QA مخصوص این فاز روی **SQLite** (اسکیمای کامل از مدل‌های واقعی؛ مهاجرت Alembic روی SQLite پشتیبانی نمی‌شود و تغییر backend/migration خارج از محدودهٔ فاز بود)؛ seedهای واقعی بک‌اند (`seed_database`) + یک کتاب آزمون `فیزیک دهم` با ۳ صفحهٔ تأییدشدهٔ فصل ۲.
- ارائه‌دهندهٔ هوش مصنوعی: یک سرور فیک OpenAI-compatible روی `:8003` که **فقط جایگزین فروشندهٔ بیرونی است** (`chat/completions` با JSON اسکریپت معتبر و `audio/speech` با WAV واقعی ۲۰ ثانیه‌ای)؛ اعتبارسنجی اسکریپت، کش TTS، مونتاژ ffmpeg، اندازه‌گیری duration، وضعیت job و همهٔ endpointها **کد واقعی بک‌اند** هستند. اپیزود از **UI واقعی** ساخته شد: ۱ درخواست اسکریپت + ۱۰ فراخوانی TTS واقعی → مونتاژ واقعی ffmpeg → `episode.mp3` واقعی 2.4MB با **duration واقعی ۲۰۰٫۳۶ ثانیه** و زمان‌بندی واقعی بخش‌ها (۰ تا ۲۰۰).
- احراز هویت: حساب A حساب dev-seed واقعی بک‌اند (`DEV_SEED_*`) و حساب B با **ثبت‌نام واقعی UI** (OTP با SMS provider دمو — کد از HMAC دیتابیس QA بازیابی شد؛ فقط ابزار محیط QA، نه بخشی از محصول). در QA `SECRET_KEY` ثابت ست شد تا HMAC بین فرآیندها یکی باشد (نکتهٔ محیطی، نه محصولی).
- شواهد: `/tmp/render_qa04b/qa_log.json` + اسکرین‌شات‌های `01..13*` + خروجی ابزارگذاری‌شدهٔ localStorage.

**۶-ب) سناریوها و نتایج (۱۶/۱۶ PASS):**

| سناریو | نتیجه | شاهد واقعی |
|---|---|---|
| ورود حساب A با فرم واقعی رمز عبور | PASS | مودال بسته شد؛ `user` شناسایی شد |
| ساخت اپیزود از UI واقعی (کتاب/فصل/قالب → تأیید) | PASS | `POST /podcasts` 202 → worker واقعی → `completed` |
| پخش با کنترل واقعی UI تا ثانیه ~۱۲۰ (۸ بار «+۱۵ ثانیه») | PASS | مینی‌پلیر: `2:04 / 3:20` |
| ذخیرهٔ موقعیت هنگام pause | PASS | `darsyar:podcast:playback:v1:54f49cb2-…` = `{"episodeId":1,"position":122.566,"speed":1,"wasPlaying":true}` |
| **Refresh کامل → بازیابی** | PASS | مینی‌پلیر ظاهر شد؛ بنر «ادامهٔ پخش از موقعیت قبلی»؛ `2:05 / 3:20` |
| «ادامه» → MediaSession در Chromium واقعی | PASS | `playbackState:"playing"`, `title:"پادکست QA فاز ۰۴ب — حرکت بر خط راست"`, `artist:"فیزیک دهم · گفت‌وگوی عمیق (Deep Dive)"`, `album:"درسیار"`؛ artwork=0 (بدون URL جلد — درست) |
| ذخیرهٔ سرعت ۱٫۵× | PASS | UI `1.5×` و `record.speed=1.5` |
| **بازیابی سرعت پس از reload** | PASS | UI `1.5×` و زمان `2:08 / 3:20` |
| جابه‌جایی SPA به `/account/profile` و بازگشت | PASS | پلیر در هر دو باقی ماند (بدون remount صدا) |
| **ادامهٔ پخش تا پایان → پاک‌سازی رکورد** | PASS | با seek عبور از پایان در حال پخش: توالی واقعی `pause → ended` → رکورد `None`؛ مینی‌پلیر به حالت «پخش» برگشت |
| خروج حساب A از UI | PASS | تأیید در مودال → `clearClientAuth` |
| ثبت‌نام واقعی حساب B (OTP) | PASS | `POST /register/request-otp` 200 → کد → رمز → حساب ساخته شد |
| **جداسازی حساب B** | PASS | بدون پلیر، بدون بنر، کتابخانهٔ خالی؛ کلیدهای playback برای B: `[]` |
| کلیدهای user-scoped پس از جابه‌جایی حساب | PASS | هیچ کلید سرریز‌شده بین حساب‌ها |
| خطاهای کنسول مرورگر | PASS | ۰ خطا |
| تکمیل اپیزود با خط لولهٔ واقعی | PASS | `status=completed`, `duration_seconds=200.359184`, `episode.mp3` واقعی |

**۶-ج) توالی واقعی رویدادها هنگام رسیدن به پایان (ابزارگذاری‌شده):**
با wrapper روی `localStorage` در صفحهٔ واقعی، هنگام seek به پایان در حال پخش این توالی ثبت شد:
`set(pos=200.32, wp=true)` (نوشتن همگام seek) → `set(pos=200.32, wp=false)` (pause) → `remove` (ended) → کلیدهای نهایی: `[]`.
یک کاوشگر کنترل‌شدهٔ Chromium هم ترتیب خام را تأیید کرد: `seeking → timeupdate(paused) → seeked → timeupdate → pause → ended`.

**۶-د) صداقت گزارش:** وجود API در Chromium headless عملکرد صفحهٔ قفل/نوتیفیکیشن رسانه‌ای سیستم‌عامل را **اثبات نمی‌کند** — آن بخش PARTIAL ثبت شده (بخش ۸). کنترل‌های درون‌صفحه (دکمه‌ها، seek، سرعت) با کلیک واقعی اثبات شده‌اند.

## ۷) یافتهٔ این نشست و اصلاح انجام‌شده

**یافته (تکرارپذیر در QA واقعی):** پس از یک بارگذاری کامل صفحه، restore جلسه را **مکث‌شده** بازمی‌گرداند (مرورگرها autoplay را می‌بلاکند). در این حالت، seek به دقیقاً انتهای فایل هیچ `pause/ended` ای-fire نمی‌کند و رکوردِ `position≈duration` به‌جا می‌ماند. جدا از آن، در سناریوی «رسیدن به پایان در حال پخش» Chromium ترتیب `pause → ended` می‌دهد؛ اگر هر رویداد دیگری بعد از `ended` بنویسد، رکورد تمام‌شده دوباره ظاهر می‌شد (در یکی از اجراها رخ داد).

**اصلاح (دو تکه، کم‌ریسک):**
1. در listener ی `pause`: اگر `element.ended` است، رکورد را پاک کن و persist نکن (مکثِ همراه پایان نباید بعد از پاک‌سازیِ `ended` دوباره «موقعیت تمام‌شده» را بنویسد).
2. در restore: اگر موقعیت ذخیره‌شده عملاً پایان فایل است، علاوه بر پاک‌سازی رکورد، بنر «ادامهٔ پخش از موقعیت قبلی» هم پنهان شود.

**حالت باقی‌ماندهٔ طراحی‌شده (پوشش‌داده‌شده):** seek به پایان **در حالت مکث** رکورد `position≈duration` می‌گذارد (کاربرِ مکث‌کرده در انتها — پایان واقعی محسوب نمی‌شود). قانون restore-near-end در بارگذاری بعدی آن را «تمام‌شده» می‌بیند: رکورد پاک، شروع از صفر، بدون بنر — با تست رگرسیون قفل شده. رفتار خطرناکی باقی نمی‌ماند.

**پس از اصلاح:** ۱۳۲ تست سبز، `tsc/eslint` پاک، build موفق، و QA کامل ۱۶/۱۶ دوباره اجرا و سبز شد.

## ۸) محدودیت‌های باقی‌مانده (صادقانه)

1. **PARTIAL — کنترل‌های رسانه‌ای سطح OS / صفحهٔ قفل:** metadata، playbackState، positionState و ثبت یک‌بارهٔ handlerها در Chromium واقعی اثبات شده‌اند و wiring در vitest قفل است؛ اما عملکرد واقعی روی دستگاه (اندروید/iOS، صفحهٔ قفل، بلوتوث) در این محیط قابل اثبات نیست — نیاز به دستگاه واقعی.
2. **بدون دستگاه واقعی:** سناریوهای «قفل صفحه» و «کنترل از هدست/نوتیفیکیشن سیستم» تست‌نشده گزارش می‌شوند، نه PASS.
3. **همگام‌سازی بین دستگاه‌ها:** خارج از scope (رکورد فقط روی همان مرورگر همان دستگاه بازیابی می‌شود).
4. **artwork جلد:** منبع تصویر جلد هنوز وجود ندارد؛ کد فقط URL معتبر `https?/data:image` را می‌پذیرد (تست‌شده).
5. **خط لوله روی PostgreSQL:** بن‌بست قفل ردیف `user_quotas` بین worker و gateway که در QA فاز قبل روی PostgreSQL مستند شد، در محدودهٔ این فاز نبود و تغییر نکرده است؛ QA این فاز روی SQLite اجرا شد (suite کامل بک‌اند روی SQLite سبز است — بخش ۵).
6. **seek به پایان در حالت مکث:** رکورد را با `position≈duration` نگه می‌دارد (طراحی؛ در بارگذاری بعدی به‌عنوان تمام‌شده پاک می‌شود — تست رگرسیون دارد).

## ۹) دستور Rollback دقیق

وضعیت مخزن: یک commit محلی پایه (`7db4f35` = اسنپ‌شات ورودی، بدون push) و **تمام کار این فاز به‌صورت تغییرات uncommitted در working tree** روی آن. دو لایهٔ بازگشت:

```bash
cd /home/z/my-project/iran-tutor-main

# لایهٔ ۱ — فقط تغییرات این نشست (اصلاح hardening + ۲ تست) را برگردانانید
# (گزارش docs/ به‌صورت اختیاری با git checkout بازمی‌گردد):
git checkout -- frontend/components/PodcastPlayerProvider.tsx frontend/tests/PodcastPlayerPersistence.test.tsx

# لایهٔ ۲ — برگشت کامل به اسنپ‌شات ورودی (کل Phase 04B حذف می‌شود):
git reset --hard 7db4f35   # یا: git checkout -- . && git clean -fd frontend/

# پس از هر لایه، بازسازی و اطمینان از سبز بودن:
cd frontend && npx vitest run && npx tsc --noEmit && npx eslint . && npm run build
```
فایل‌های QA این نشست (`.env`، `qa04b_qa.sqlite3`، `backend/storage/`) gitignored هستند و در هیچ لایه‌ای وارد مخزن نشده‌اند؛ برای پاک‌سازی کامل محیط: `rm -f backend/.env backend/qa04b_qa.sqlite3 && rm -rf backend/storage/podcast_audio backend/storage/tts_cache` و توقف فرآیندهای `uvicorn`/`next start`/`fake_provider`.

## ۱۰) حکم نهایی

**`PASS — PERSISTENT PLAYBACK & MEDIASESSION VERIFIED (this session)`**

| معیار | شرط پذیرش | حکم |
|---|---|---|
| ذخیره موقعیت | نوشتن throttle دار + اجباری در pause/pagehide | **PASS** (شاهد: رکورد واقعی در کلید user-scoped) |
| بازیابی پس از Reload | اپیزود/موقعیت/بنر/زمان درست | **PASS** (`2:05 / 3:20` پس از refresh کامل) |
| بازیابی سرعت | `1.5×` پس از reload | **PASS** |
| جداسازی کاربران | کلید per-user؛ حساب B هیچ اثری از A نمی‌بیند | **PASS** (+ تست‌های vitest) |
| MediaSession | metadata/playbackState/positionState در Chromium واقعی | **PASS** |
| کنترل‌های رسانه | play/pause/seekbackward/seekforward/seekto؛ ۱۵ ثانیه؛ یک element سراسری | **PASS** (OS-level: PARTIAL — بند ۸-۱) |
| پخش بین صفحات | SPA away/back با پلیر پایدار | **PASS** |
| عدم Regression | ۱۳۲ تست فرانت + suite بک‌اند + تفاوت‌های محدود در working tree | **PASS** |
| Production Build | `next build` موفق | **PASS** |
| QA مرورگر | ۱۶/۱۶ گام با شواهد واقعی | **PASS** |

درست‌کردن «PASS فرضی» جایز نبود؛ تنها مواردی که در این محیط اساساً قابل اثبات نیستند (کنترل‌های سطح دستگاه) صادقانه PARTIAL ثبت شده‌اند.
