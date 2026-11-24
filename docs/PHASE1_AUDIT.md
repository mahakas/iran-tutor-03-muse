# بازبینی فاز ۱ — پیش از شروع فاز ۲

**تاریخ:** ۲۱ نوامبر ۲۰۲۶
**شاخه:** `arena/7aab5e89-iran-tutor`
**کامیت مبنا (فاز ۱):** `adcc32c`
**دامنه:** بازبینی سه‌بندی درخواستی روی فاز ۱، **بدون** هیچ تغییری در دامنهٔ فاز ۲.

> نتیجهٔ کلی: **هر سه بند پاس شد.** دو نقطهٔ نشت واقعی و دو مسیر دور‌زدن از دروازهٔ مرکزی پیدا و رفع شد؛ برای هر سه بند محافظ خودکار (test) اضافه شد تا بازگشت رگرسیون ممکن نباشد. **فاز ۲ آغاز نشده است.**

---

## بند ۱ — هیچ فراخوانی مستقیم LLM / Vision / STT / Embedding بیرون از `ai_gateway`

### ۱-۱. وضعیت یافته‌شده

| مکان | نوع | حکم |
|---|---|---|
| `app/core/llm_client.py` | تنها جایی که SDK `openai` وارد می‌شود | ✅ مجاز (پیاده‌سازی زیرین دروازه) |
| `app/services/ai_gateway.py` | تنها مصرف‌کنندهٔ `llm_client` برای استنتاج | ✅ دروازهٔ مرکزی |
| `app/api/admin.py` `/settings/test-ai` | **httpx خام به `{base}/models` + `{base}/chat/completions`** | ❌ دور‌زدن از دروازه → **رفع شد** |
| `app/api/admin.py` `/settings/test-vector` | **httpx خام به Qdrant `{url}/collections`** | ❌ حمل‌ونقل در لایهٔ API → **منتقل شد** |
| `app/api/{tutor,exams}.py` | `track_token_usage` | ✅ فقط شمارندهٔ مصرف، نه فراخوانی AI |
| `app/{main,runtime_config}.py` | `close_llm_clients` | ✅ بستن استخر اتصال در lifespan |
| `scripts/test_llm.py` | `vision_json` مستقیم | ❌ → **از دروازه عبور می‌کند** |
| `scripts/verify_ai_stack.py` | `complete_text` / `complete_json` / `vision_json` / `embed_texts` مستقیم | ❌ → **همه از دروازه** |

### ۱-۲. راه‌حل

**`ai_gateway.probe_endpoint(...)` جدید** — تنها جایی در کل کدبیس که بیرون از یک فراخوانی عادی دروازه به یک ارائه‌دهنده حرف می‌زند (`/models` + یک `/chat/completions` کوچک). هر دو مسیر تست اتصال ادمین از آن عبور می‌کنند:

- `POST /admin/providers/{id}/test` → `probe_provider()` که اکنون یک پوشش نازک روی `probe_endpoint` است
- `POST /admin/settings/test-ai` → مستقیم `probe_endpoint` را صدا می‌زند

`probe_endpoint` خودش کلید را در همهٔ رشته‌های خطا پاک می‌کند (`_scrub`)، پس مسیر `test-ai` هم مثل بقیه دیگر هیچ کلیدی را بازنمی‌گرداند.

**`retrieval_service.probe_qdrant(url, collection)` جدید** — تنها HTTP خام Qdrant؛ `/settings/test-vector` به آن واگذار شد. `app/api/admin.py` حالا **هیچ import‌ای از `httpx` ندارد**.

**اسکریپت‌های CLI** حالا از `complete_text_via_gateway`, `complete_json_via_gateway`, `vision_json_via_gateway`, `embed_via_gateway` استفاده می‌کنند، یعنی دقیقاً همان مسیری که ترافیک واقعی طی می‌کند (با مسیریابی و ثبت audit).

### ۱-۳. سنجهٔ بازگشت‌ناپذیر

`backend/tests/test_ai_gateway_isolation.py` — ۵ تست معماری که build را می‌شکنند اگر:

1. `openai` یا `anthropic` در جایی جز `app/core/llm_client.py` import شود
2. `AsyncOpenAI`/`OpenAI`/`AsyncAnthropic`/`Anthropic` بیرون از wrapper ساخته شود
3. هر فایلی جز `ai_gateway.py` به `chat/completions`، `/embeddings`، `/audio/transcriptions` یا `/audio/speech` اشاره کند
4. کسی بیرون از allowlist، چیزی جز `track_token_usage` / `close_llm_clients` از `app.core.llm_client` import کند
5. یکی از helperهای دروازه (`complete_text`, `complete_json`, `vision_json`, `transcribe_audio`, `embed`, `probe_endpoint`) حذف شود

> اعتبار تست با کنترل منفی سنجیده شد: افزودن `complete_text` به importهای `app/api/tutor.py` بلافاصله تست را شکست (۱ failed از ۵).

---

## بند ۲ — همهٔ مسیرهای `/api/v1/admin/*` واقعاً محافظت‌شده‌اند و کلید لو نمی‌رود

### ۲-۱. پوشش احراز هویت — شمارش ساختاری

روی اپ واقعی (۹۸ عملیات، ۷۹ مسیر) شمارش شد:

| دسته | تعداد |
|---|---|
| عملیات زیر `/api/v1/admin` | **۴۹** |
| محافظت‌شده با `require_admin` | **۴۶** |
| عمداً عمومی (`/admin/auth/{login,logout,session}`) | **۳** |
| **بدون محافظت** | **۰** ✅ |

این شمارش حالا یک تست دائمی است: `test_every_admin_operation_carries_require_admin` در `tests/test_phase1_governance.py`. اگر کسی فردا یک روت ادمین بدون guard اضافه کند، تست می‌شکند (و تعداد روت‌های عمومی هم دقیقاً ۳ قفل شده است).

### ۲-۲. نشت کلید — دو یافتهٔ واقعی

**(الف) `serialize_provider(reveal=True)` — مسیر مرده اما خطرناک.**
تابع یک پارامتر `reveal` داشت که کلید را رمزگشایی و **plaintext** برمی‌گرداند. هیچ‌جا صدا زده نمی‌شد، ولی هر توسعه‌دهندهٔ بعدی می‌توانست با یک پرچم آن را روشن کند. **پارامتر حذف شد**؛ `api_key` حالا همیشه `None` است و فقط برای تمایز «تغییر نکرده» از «پاک شده» وجود دارد. docstring صریحاً می‌گوید هیچ endpointی مجاز به بازگرداندن کلید نیست.

**(ب) کلیدهای secret سراسری در `system_config` — درست بود، اما تست‌نشده.**
`serialize_admin_settings` فقط `{configured, masked, source}` برمی‌گرداند و `mask_secret` حداکثر ۴+۴ کاراکتر نشان می‌دهد. تأیید شد که `GET /admin/settings` و `GET /admin/billing` هیچ کلیدی برنمی‌گردانند — اما هیچ تستی این را قفل نکرده بود.

### ۲-۳. سنجهٔ بازگشت‌ناپذیر

`test_no_admin_response_ever_contains_a_plaintext_secret` — **جاروی کامل**:

- یک ارائه‌دهندهٔ واقعی با کلید `sk-LEAKCANARY-provider-…` در vault رمزنگاری‌شده ساخته می‌شود
- `system_config` با `llm_api_key` و `sms_api_key` واقعی پر می‌شود
- **همهٔ GETهای بدون پارامتر زیر `/admin`** (به‌جز `auth/*`) یکی‌یکی صدا زده می‌شوند
- بدنهٔ هر پاسخ اسکن می‌شود: هیچ‌کدام از چهار رشتهٔ canary نباید ظاهر شود
- **کل لاگ‌های pytest (`caplog` در DEBUG)** هم اسکن می‌شوند
- در پایان تأیید می‌شود که ماسک هنوز کار می‌کند (`api_key: null`, `api_key_masked` با ۴ کاراکتر آخر, `has_api_key: true`) تا «لو نرفتن» از راه «خراب کردن ماسک» به دست نیامده باشد

> اعتبار با کنترل منفی: برگرداندن `"api_key": decrypt_secret(...)` به serializer بلافاصله تست را شکست.

در همین حین، تزریق `async_session_factory` برای ماژول‌های API در fixture تست اضافه شد تا روت‌هایی که خودشان session باز می‌کنند (settings/books/users) به دیتابیس ایزولهٔ تست بروند، نه Postgres واقعی.

### ۲-۴. تأیید زنده (سرور در حال اجرا روی `:8000`)

با یک «ارائه‌دهندهٔ تله» محلی که عمداً کلید را در بدنهٔ خطا بازمی‌گرداند:

```
POST /admin/settings/test-ai   (بدون توکن)                    → 401
POST /admin/settings/test-ai   (کلید = sk-LEAKCANARY-live-…)  → 200
  error: {"error":"invalid key: Bearer ***"}
  prompt_test.error: {"error":"invalid key: Bearer ***"}
  تعداد رخداد LEAKCANARY در پاسخ: 0
POST /admin/settings/test-vector (Qdrant غیرقابل‌دسترس)        → ok:false, detail: عدم دسترسی…
POST /admin/providers {api_key: sk-LEAKCANARY-…}              → api_key: null, api_key_masked: "sk-...7890"
GET  /admin/providers                                          → LEAKCANARY: 0
لاگ سرور                                                       → LEAKCANARY: 0
```

یعنی حتی وقتی upstream خودِ کلید را echo می‌کند، هم پاسخ API و هم لاگ سرور تمیز می‌مانند.

---

## بند ۳ — تست‌ها و build

| سنجه | فرمان | نتیجه |
|---|---|---|
| بک‌اند | `.venv/bin/python -m pytest -q` | ✅ **۱۴۰ passed in 8.41s** |
| نوع‌ها | `npx tsc --noEmit` | ✅ EXIT 0 |
| لینت | `npm run lint` | ✅ EXIT 0 |
| build فرانت | `npm run build` | ✅ EXIT 0 — **۱۶ مسیر** |
| لینت استاتیک پایتون | `pyflakes app/ tests/ scripts/` | ✅ بدون خطای جدید |
| سطح API | `import app.main` | ۹۸ عملیات / ۷۹ مسیر (بدون تغییر) |

**تفکیک تست‌های اضافه‌شده در این بازبینی (۷ تست):**

- `test_ai_gateway_isolation.py` — ۵ تست معماری (بند ۱)
- `test_every_admin_operation_carries_require_admin` (بند ۲-۱)
- `test_no_admin_response_ever_contains_a_plaintext_secret` (بند ۲-۳)

تست‌های موجود هم به‌روز شدند: `test_admin_control_center.py` حالا به‌جای patch کردن `admin_api.httpx.AsyncClient`، seamهای `ai_gateway.probe_endpoint` و `retrieval_service.probe_qdrant` را patch می‌کند.

`frontend/next-env.d.ts` (که `next build` بازنویسی می‌کند) پیش از کامیت بازگردانده شد.

---

## فایل‌های تغییر‌یافته

| فایل | تغییر |
|---|---|
| `backend/app/services/ai_gateway.py` | +`probe_endpoint` (حمل‌ونقل واحد probe)؛ `probe_provider` روی آن بازنویسی شد |
| `backend/app/services/retrieval_service.py` | +`probe_qdrant`؛ +`import time`, `urlparse` |
| `backend/app/services/ai_provider_service.py` | حذف `reveal`؛ `api_key` همیشه `None` |
| `backend/app/api/admin.py` | `test-ai` و `test-vector` واگذار شدند؛ `import httpx` حذف شد (−۱۷۳ خط) |
| `backend/scripts/test_llm.py` | عبور از `vision_json_via_gateway` |
| `backend/scripts/verify_ai_stack.py` | هر چهار بررسی از دروازه عبور می‌کنند |
| `backend/tests/test_ai_gateway_isolation.py` | **جدید** — ۵ تست معماری |
| `backend/tests/test_phase1_governance.py` | +۲ تست جارویی؛ fixture حالا `async_session_factory` را تزریق می‌کند |
| `backend/tests/test_admin_control_center.py` | patch کردن seamهای سرویس به‌جای httpx |

---

## وضعیت فاز ۲

**آغاز نشده.** طبق دستور، تا تأیید صریح کارفرما هیچ کدی از فاز ۲ نوشته نمی‌شود.
