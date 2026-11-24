"""Reference data for the Iran Education Catalog 1405–1406.

Source: the owner-provided catalog
`darsyar_complete_grade_first_list_1405-1406 (1).md`
(catalog key: darsyar_iran_education_catalog_1405-1406).

Rules encoded here:
- Titles are copied verbatim from the catalog — never rewritten.
- No official national code is invented; unknown codes stay NULL.
- A book common to several programs is one record expanded by the importer.
- Uncertain items (experimental, regional, unverified grade/code) carry their
  own status flags; they are never silently turned into confirmed data.
- No vocational-specialist or Kardanesh textbooks in this stage (owner decision).
"""

from __future__ import annotations

# ─── Vocational grounds (زمینه) per هنرستانی track ─────────────────────────────

GROUND_SPECS: list[tuple[str, str, list[tuple[str, str]]]] = [
    # (branch_code, ground_code, ground_title)
    ("technical_vocational", "industry", "صنعت"),
    ("technical_vocational", "services", "خدمات"),
    ("technical_vocational", "art", "هنر"),
    ("technical_vocational", "agriculture", "کشاورزی"),
    ("kar_danesh", "industry", "صنعت"),
    ("kar_danesh", "services", "خدمات"),
    ("kar_danesh", "art", "هنر"),
    ("kar_danesh", "agriculture", "کشاورزی"),
]

# Program lists exactly as given by the owner (working list — validity status is
# set to needs_verification for every entry; no program is marked active on
# unverified evidence).
TVO_PROGRAMS: dict[str, list[str]] = {
    "industry": [
        "الکتروتکنیک",
        "برق صنعتی",
        "الکترونیک",
        "الکترونیک و مخابرات دریایی",
        "شبکه و نرم‌افزار رایانه",
        "تأسیسات مکانیکی",
        "چاپ",
        "صنایع چوب و مبلمان",
        "صنایع فلزی",
        "صنایع نساجی",
        "ماشین ابزار",
        "معماری داخلی",
        "ساختمان",
        "مکاترونیک",
        "مکانیک خودرو",
        "مکانیک موتورهای دریایی",
        "صنایع شیمیایی",
        "متالورژی",
        "سرامیک",
        "معدن",
    ],
    "services": [
        "حسابداری",
        "تربیت کودک",
        "تربیت بدنی",
        "حمل‌ونقل جاده‌ای",
        "ناوبری",
    ],
    "art": [
        "طراحی و دوخت",
        "پویانمایی",
        "سینما",
        "تولید برنامه تلویزیونی",
        "صنایع دستی ـ فرش",
        "صنایع دستی ـ هنر سرامیک",
        "صنایع دستی ـ هنرهای چوبی",
        "گرافیک",
        "فتوگرافیک",
        "موسیقی ـ نوازندگی ساز ایرانی",
        "موسیقی ـ نوازندگی ساز جهانی",
        "نقاشی",
        "نمایش",
    ],
    "agriculture": [
        "امور باغی",
        "امور زراعی",
        "دامپروری",
        "شیلات",
        "صنایع غذایی",
        "ماشین‌های کشاورزی",
    ],
}

KARDANESH_PROGRAMS: dict[str, list[str]] = {
    "industry": [
        "نصب و سرویس آسانسور",
        "عیب‌یابی و مونتاژ سیستم‌های رایانه‌ای",
        "تعمیر تلفن",
        "تعمیر دستگاه اداری",
        "تعمیر ابزار دقیق",
        "تولید و توسعه پایگاه اینترنتی",
        "تولید محتوای آموزشی الکترونیکی",
        "تأسیسات سرمایشی",
        "تأسیسات ساختمانی",
        "اپراتور CNC چوب",
        "نقشه‌کشی صنعتی",
        "نقشه‌کشی ساختمان",
        "کارهای عمومی ساختمان",
        "تعمیر خودروهای تجاری",
        "خدمات پس از فروش خودرو",
        "صافکاری و نقاشی خودرو",
        "تعمیر ماشین‌آلات راه‌سازی",
        "تعمیر و نگهداری هواپیما",
        "تعمیرات ناوگان ریلی",
        "خط و سازه‌های فنی راه‌آهن",
        "مدل‌سازی",
        "آبکاری فلزات",
        "ریخته‌گری",
        "پلاستیک‌کاری",
    ],
    "services": [
        "امور اداری",
        "بورس و اوراق بهادار",
        "تربیت کودک",
        "مددکاری سالمندان",
        "مددکاری افراد با نیازهای ویژه",
        "بهیاری",
        "دستیار طرح تمرین فوتبال",
        "ایمنی و آتش‌نشانی",
        "راهبری جرثقیل",
        "خدمات فروشگاهی",
        "بازیافت مواد و انرژی",
        "مهمانداری هواپیما",
        "مدیریت آشپزی و قنادی",
        "هتلداری",
        "راهنمای گردشگری",
    ],
    "art": [
        "نان و شیرینی",
        "دوخت لباس محلی",
        "دوخت‌های سنتی",
        "سراجی و کیف",
        "تولید کفش",
        "تصویرسازی",
        "طراحی فرش",
        "طراحی طلا و جواهر",
        "جواهرسازی",
        "تراش شیشه و کریستال",
        "قلم‌زنی",
        "تراش سنگ‌های قیمتی",
        "آینه‌کاری",
        "گرافیک رایانه‌ای",
        "عکاسی دیجیتال",
        "چندرسانه‌ای",
        "سازسازی",
        "نوازندگی",
        "آواز",
        "نگارگری",
        "تذهیب",
        "چهره‌سازی",
        "نقاشی ایرانی",
        "چهره‌پردازی",
        "چاپ باتیک و سیلک",
        "صحافی",
        "سینما",
        "گرافیک",
        "نمایش",
    ],
    "agriculture": [
        "امور زراعی و باغی",
        "دامپروری",
        "شیلات",
        "صنایع غذایی",
        "ماشین‌های کشاورزی",
        "محیط‌بانی",
    ],
}

THEORETICAL_FIELD_CODES = ["math_physics", "experimental", "humanities", "islamic_studies"]

# ─── Elementary and lower-secondary books (grades 1–9) ─────────────────────────
# Each entry: (title, flags-dict). flags keys: kind, subject (slug), impl, geo,
# validity, note, alt, mandatory(False → optional link).

PRIMARY_BOOKS: dict[int, list[tuple[str, dict[str, object]]]] = {
    1: [
        ("فارسی", {}),
        ("فارسی می‌خوانم", {"validity": "needs_verification", "note": "عنوان هم‌پوشان/نونگاشت پایهٔ اول؛ شمول هر مدرسه از رکورد سال جاری کنترل شود."}),
        ("فارسی می‌نویسم", {"validity": "needs_verification", "note": "عنوان هم‌پوشان/نونگاشت پایهٔ اول؛ شمول هر مدرسه از رکورد سال جاری کنترل شود."}),
        ("نگارش فارسی", {"subject": "negarsh"}),
        ("آموزش قرآن", {}),
        ("ریاضی", {}),
        ("علوم تجربی", {}),
        ("جهان پیرامون", {}),
        ("هنر و خلاقیت", {}),
        ("حرکت و بازی", {}),
        ("ریاضی دوست‌داشتنی", {"impl": "experimental", "validity": "needs_verification", "mandatory": False, "note": "اجرای آزمایشی؛ شمول سراسری فرض نشود و بدون بررسی به‌عنوان کتاب اجباری قطعی ثبت نشود."}),
        ("آموزش قرآن بخش اول", {"impl": "experimental", "validity": "needs_verification", "mandatory": False, "note": "اجرای آزمایشی؛ عنوان هم‌پوشان با آموزش قرآن — شمول نیازمند بررسی."}),
    ],
    2: [
        ("فارسی", {}),
        ("نگارش فارسی", {"subject": "negarsh"}),
        ("ریاضی", {}),
        ("علوم تجربی", {}),
        ("آموزش قرآن", {}),
        ("هدیه‌های آسمان", {}),
        ("از ایرانمان دفاع می‌کنیم", {"subject": None, "kind": "periodical", "grade": None, "impl": "needs_verification", "validity": "needs_verification", "mandatory": False, "note": "کتاب مکمل دوره‌ای؛ پایهٔ دقیق تخصیص (دورهٔ دوم ابتدایی و متوسطهٔ اول) در بستهٔ رسمی مدرسه کنترل شود — به پایهٔ مشخصی منتسب نشده است."}),
    ],
    3: [
        ("فارسی", {}),
        ("نگارش فارسی", {"subject": "negarsh"}),
        ("ریاضی", {}),
        ("علوم تجربی", {}),
        ("آموزش قرآن", {}),
        ("هدیه‌های آسمان", {}),
        ("مطالعات اجتماعی", {}),
    ],
    4: [
        ("فارسی", {}),
        ("نگارش فارسی", {"subject": "negarsh"}),
        ("ریاضی", {}),
        ("علوم تجربی", {}),
        ("آموزش قرآن", {}),
        ("هدیه‌های آسمان", {}),
        ("مطالعات اجتماعی", {}),
        ("آموزش خط تحریری", {"subject": "khatt-tahriri", "kind": "supplementary", "note": "کتاب کار/مکمل — از کتاب درسی اصلی جدا نگهداری می‌شود."}),
    ],
    5: [
        ("فارسی", {}),
        ("نگارش فارسی", {"subject": "negarsh"}),
        ("ریاضی", {}),
        ("علوم تجربی", {}),
        ("آموزش قرآن", {}),
        ("هدیه‌های آسمان", {}),
        ("مطالعات اجتماعی", {}),
        ("آموزش خط تحریری", {"subject": "khatt-tahriri", "kind": "supplementary", "note": "کتاب کار/مکمل — از کتاب درسی اصلی جدا نگهداری می‌شود."}),
    ],
    6: [
        ("فارسی", {}),
        ("نگارش فارسی", {"subject": "negarsh"}),
        ("ریاضی", {}),
        ("علوم تجربی", {}),
        ("آموزش قرآن", {}),
        ("هدیه‌های آسمان", {}),
        ("مطالعات اجتماعی", {}),
        ("تفکر و پژوهش", {}),
        ("کار و فناوری", {}),
        ("آموزش خط تحریری", {"subject": "khatt-tahriri", "kind": "supplementary", "note": "کتاب کار/مکمل — از کتاب درسی اصلی جدا نگهداری می‌شود."}),
    ],
}

LOWER_SECONDARY_BOOKS: dict[int, list[tuple[str, dict[str, object]]]] = {
    7: [
        ("ریاضی", {}),
        ("علوم تجربی", {}),
        ("فارسی", {}),
        ("نگارش", {"subject": "negarsh"}),
        ("آموزش قرآن", {}),
        ("از من تا خدا", {"subject": "az-man-ta-khoda", "impl": "confirmed", "geo": "national", "note": "اجرای سراسری پایهٔ هفتم در سال تحصیلی ۱۴۰۵–۱۴۰۶ طبق کاتالوگ مالک."}),
        ("زبان انگلیسی", {"subject": "english"}),
        ("کتاب کار زبان انگلیسی", {"subject": "english", "kind": "workbook"}),
        ("عربی", {"subject": "arabic"}),
        ("مطالعات اجتماعی", {}),
        ("کار و فناوری", {}),
        ("فرهنگ و هنر", {"subject": "farhang-honar"}),
        ("تفکر و سبک زندگی", {"subject": "tafakkor-sabk-zendegi", "validity": "needs_verification", "note": "نسخهٔ دختران/پسران در صورت ارائهٔ مجزا — تا ابلاغ، یک رکورد عمومی ثبت شده است."}),
        ("از ایرانمان دفاع می‌کنیم", {"subject": None, "kind": "periodical", "grade": None, "impl": "needs_verification", "validity": "needs_verification", "mandatory": False, "note": "کتاب مکمل دوره‌ای؛ پایهٔ دقیق تخصیص در بستهٔ رسمی مدرسه کنترل شود — رکورد مشترک با دورهٔ دوم ابتدایی."}),
    ],
    8: [
        ("ریاضی", {}),
        ("علوم تجربی", {}),
        ("فارسی", {}),
        ("نگارش", {"subject": "negarsh"}),
        ("آموزش قرآن", {}),
        ("زبان انگلیسی (۲)", {"subject": "english"}),
        ("کتاب کار انگلیسی (۲)", {"subject": "english", "kind": "workbook"}),
        ("عربی", {"subject": "arabic"}),
        ("مطالعات اجتماعی", {}),
        ("کار و فناوری", {}),
        ("فرهنگ و هنر", {"subject": "farhang-honar"}),
        ("تفکر و سبک زندگی", {"subject": "tafakkor-sabk-zendegi"}),
        ("از من تا خدا", {"subject": "az-man-ta-khoda", "impl": "regional_pilot", "geo": "provincial", "validity": "needs_verification", "mandatory": False, "note": "در سال تحصیلی ۱۴۰۵–۱۴۰۶ فقط در استان‌ها/مدارس مجری؛ برای همهٔ مدارس کشور قطعی تخصیص نیافته است."}),
    ],
    9: [
        ("ریاضی", {}),
        ("علوم تجربی", {}),
        ("فارسی", {}),
        ("نگارش", {"subject": "negarsh"}),
        ("آموزش قرآن", {}),
        ("پیام‌های آسمان", {"subject": "payam-haye-aseman", "alt": "tarbiat-dini-9", "note": "بر اساس برنامهٔ ابلاغی مدرسه و استان؛ جایگزینِ «از من تا خدا» در همین گروه انتخابی است."}),
        ("از من تا خدا", {"subject": "az-man-ta-khoda", "impl": "regional_pilot", "geo": "provincial", "validity": "needs_verification", "mandatory": False, "alt": "tarbiat-dini-9", "note": "در برخی استان‌ها/مدارس مجری؛ اجرای سراسری پایهٔ نهم فرض نشود — جایگزین «پیام‌های آسمان» است و هرگز هم‌زمان اجباری نیست."}),
        ("زبان انگلیسی (۳)", {"subject": "english"}),
        ("کتاب کار انگلیسی (۳)", {"subject": "english", "kind": "workbook"}),
        ("عربی", {"subject": "arabic"}),
        ("مطالعات اجتماعی", {}),
        ("کار و فناوری", {}),
        ("فرهنگ و هنر", {"subject": "farhang-honar"}),
        ("آمادگی دفاعی", {"subject": "amadegi-defaee"}),
    ],
}
