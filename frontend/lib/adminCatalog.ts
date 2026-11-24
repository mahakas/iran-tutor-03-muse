// Admin education-catalog management — entity configs for the generic manager.
// Every admin catalog page is a thin wrapper around AdminCatalogManager driven
// by one of these configs; modules stay small, typed and independently linked.

export type AdminCatalogFieldType = "text" | "number" | "bool" | "select" | "textarea";

export type AdminCatalogField = {
  name: string;
  label: string;
  type: AdminCatalogFieldType;
  required?: boolean;
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
  /** Options come from another catalog entity (FK picker), loaded at runtime. */
  from?: "cycles" | "branches" | "grounds" | "fields" | "subjects" | "textbooks" | "academic-years" | "grades";
  /** Only offer options matching this branch code (grounds/fields pickers). */
  filterByBranch?: boolean;
  hideInTable?: boolean;
};

export type AdminCatalogColumn = {
  name: string;
  label: string;
  kind?: "bool" | "badge" | "date" | "title";
};

export type AdminCatalogFilter = {
  name: string;
  label: string;
  options?: { value: string; label: string }[];
  from?: "cycles" | "branches" | "grounds" | "fields" | "subjects" | "academic-years" | "grades" | "textbooks";
};

export type AdminCatalogEntityConfig = {
  entity: string;
  title: string;
  description: string;
  columns: AdminCatalogColumn[];
  fields: AdminCatalogField[];
  filters: AdminCatalogFilter[];
  sortable: string[];
  canArchive: boolean;
  /** Special capabilities surfaced in the manager toolbar. */
  supportsPdfUpload?: boolean;
  supportsYearCopy?: boolean;
};

const YES_NO = (label: string): AdminCatalogField => ({
  name: "is_active",
  label,
  type: "bool",
});

export const VALIDITY_OPTIONS = [
  { value: "needs_verification", label: "نیازمند راستی‌آزمایی" },
  { value: "unknown", label: "نامشخص" },
  { value: "active", label: "فعال (مستند رسمی)" },
  { value: "stopped_development", label: "توقف توسعه" },
  { value: "redesigned", label: "بازطراحی" },
  { value: "expired", label: "منقضی" },
  { value: "inactive", label: "غیرفعال" },
];

export const AUDIENCE_OPTIONS = [
  { value: "general", label: "عمومی" },
  { value: "girls", label: "ویژهٔ دختران" },
  { value: "boys", label: "ویژهٔ پسران" },
  { value: "religious_minority", label: "ویژهٔ اقلیت‌های دینی" },
];

export const KIND_OPTIONS = [
  { value: "student_book", label: "کتاب اصلی دانش‌آموز" },
  { value: "workbook", label: "کتاب کار" },
  { value: "supplementary", label: "کتاب مکمل" },
  { value: "periodical", label: "کتاب دوره‌ای" },
  { value: "teacher_guide", label: "راهنمای معلم" },
];

export const COURSE_KIND_OPTIONS = [
  { value: "general", label: "عمومی" },
  { value: "specialized", label: "تخصصی" },
  { value: "skill", label: "مهارتی" },
  { value: "workshop", label: "کارگاهی" },
  { value: "elective", label: "انتخابی" },
  { value: "supplementary", label: "مکمل" },
];

export const VALIDITY_FILTERS: AdminCatalogFilter[] = [
  { name: "validity_status", label: "وضعیت اعتبار", options: VALIDITY_OPTIONS },
];

export const ADMIN_CATALOG_ENTITIES: Record<string, AdminCatalogEntityConfig> = {
  cycles: {
    entity: "cycles",
    title: "مدیریت دوره‌های تحصیلی",
    description: "دوره‌های ابتدایی، متوسطهٔ اول و دوم — ایجاد، ویرایش، فعال/غیرفعال و حذف امن.",
    columns: [
      { name: "code", label: "کد" },
      { name: "title", label: "عنوان", kind: "title" },
      { name: "sort_order", label: "ترتیب" },
      { name: "is_active", label: "فعال", kind: "bool" },
    ],
    fields: [
      { name: "code", label: "کد (slug)", type: "text", required: true },
      { name: "title", label: "عنوان", type: "text", required: true },
      { name: "sort_order", label: "ترتیب", type: "number" },
      { name: "is_active", label: "فعال", type: "bool" },
    ],
    filters: [],
    sortable: ["id", "code", "title", "sort_order"],
    canArchive: true,
  },
  grades: {
    entity: "grades",
    title: "مدیریت پایه‌ها و کلاس‌ها",
    description: "پایه‌های ۱ تا ۱۲ با اتصال به دوره؛ شمارهٔ تکراری و اتصال ناسازگار رد می‌شود.",
    columns: [
      { name: "number", label: "شماره" },
      { name: "title", label: "عنوان", kind: "title" },
      { name: "cycle_title", label: "دوره" },
      { name: "is_active", label: "فعال", kind: "bool" },
    ],
    fields: [
      { name: "number", label: "شمارهٔ پایه (۱–۱۲)", type: "number", required: true, min: 1, max: 12 },
      { name: "title", label: "عنوان", type: "text", required: true },
      { name: "cycle_id", label: "دورهٔ تحصیلی", type: "select", from: "cycles", required: true },
      { name: "has_major", label: "پایهٔ رشته‌دار (۱۰+)", type: "bool" },
      { name: "is_active", label: "فعال", type: "bool" },
    ],
    filters: [{ name: "cycle_id", label: "دوره", from: "cycles" }],
    sortable: ["id", "number", "title"],
    canArchive: true,
  },
  branches: {
    entity: "branches",
    title: "مدیریت شاخه‌ها",
    description: "نظری، فنی‌وحرفه‌ای و کاردانش با بازهٔ پایهٔ مجاز.",
    columns: [
      { name: "code", label: "کد" },
      { name: "title", label: "عنوان", kind: "title" },
      { name: "min_grade", label: "از پایه" },
      { name: "max_grade", label: "تا پایه" },
      { name: "is_active", label: "فعال", kind: "bool" },
    ],
    fields: [
      { name: "code", label: "کد (slug)", type: "text", required: true },
      { name: "title", label: "عنوان", type: "text", required: true },
      { name: "min_grade", label: "از پایه", type: "number", min: 10, max: 12 },
      { name: "max_grade", label: "تا پایه", type: "number", min: 10, max: 12 },
      { name: "sort_order", label: "ترتیب", type: "number" },
      { name: "is_active", label: "فعال", type: "bool" },
    ],
    filters: [],
    sortable: ["id", "sort_order", "title"],
    canArchive: true,
  },
  grounds: {
    entity: "grounds",
    title: "مدیریت زمینه‌ها",
    description: "صنعت، خدمات، هنر و کشاورزی — فقط برای شاخه‌های فنی‌وحرفه‌ای و کاردانش.",
    columns: [
      { name: "code", label: "کد" },
      { name: "title", label: "عنوان", kind: "title" },
      { name: "branch_title", label: "شاخه" },
      { name: "is_active", label: "فعال", kind: "bool" },
    ],
    fields: [
      { name: "branch_id", label: "شاخهٔ هنرستانی", type: "select", from: "branches", required: true },
      { name: "code", label: "کد (industry/services/art/agriculture)", type: "text", required: true },
      { name: "title", label: "عنوان", type: "text", required: true },
      { name: "sort_order", label: "ترتیب", type: "number" },
      { name: "is_active", label: "فعال", type: "bool" },
    ],
    filters: [{ name: "branch_id", label: "شاخه", from: "branches" }],
    sortable: ["id", "sort_order", "title"],
    canArchive: true,
  },
  fields: {
    entity: "fields",
    title: "مدیریت رشته‌ها",
    description: "رشته‌های نظری (بدون زمینه) و رشته‌های هنرستانی (با زمینهٔ الزامی).",
    columns: [
      { name: "code", label: "کد" },
      { name: "title", label: "عنوان", kind: "title" },
      { name: "branch_title", label: "شاخه" },
      { name: "ground_title", label: "زمینه" },
      { name: "is_active", label: "فعال", kind: "bool" },
    ],
    fields: [
      { name: "branch_id", label: "شاخه", type: "select", from: "branches", required: true },
      { name: "ground_id", label: "زمینه (فقط هنرستانی)", type: "select", from: "grounds" },
      { name: "code", label: "کد (slug یکتا)", type: "text", required: true },
      { name: "title", label: "عنوان", type: "text", required: true },
      { name: "sort_order", label: "ترتیب", type: "number" },
      { name: "is_active", label: "فعال", type: "bool" },
    ],
    filters: [
      { name: "branch_id", label: "شاخه", from: "branches" },
      { name: "ground_id", label: "زمینه", from: "grounds" },
    ],
    sortable: ["id", "sort_order", "title", "code"],
    canArchive: true,
  },
  subjects: {
    entity: "subjects",
    title: "مدیریت درس‌ها و مواد درسی",
    description: "درس‌های عمومی/تخصصی/مهارتی با ساعت هفتگی و وضعیت اجباری.",
    columns: [
      { name: "code", label: "کد" },
      { name: "title", label: "عنوان", kind: "title" },
      { name: "course_kind", label: "نوع" },
      { name: "weekly_hours", label: "ساعت هفتگی" },
      { name: "is_mandatory", label: "اجباری", kind: "bool" },
      { name: "is_active", label: "فعال", kind: "bool" },
    ],
    fields: [
      { name: "code", label: "کد (slug یکتا)", type: "text", required: true },
      { name: "title", label: "عنوان درس", type: "text", required: true },
      { name: "course_kind", label: "نوع درس", type: "select", options: COURSE_KIND_OPTIONS },
      { name: "weekly_hours", label: "ساعت هفتگی", type: "number", min: 0, max: 40 },
      { name: "is_mandatory", label: "اجباری", type: "bool" },
      { name: "description", label: "توضیح", type: "textarea", hideInTable: true },
      { name: "is_active", label: "فعال", type: "bool" },
    ],
    filters: [{ name: "course_kind", label: "نوع درس", options: COURSE_KIND_OPTIONS }],
    sortable: ["id", "code", "title"],
    canArchive: true,
  },
  textbooks: {
    entity: "textbooks",
    title: "مدیریت کتاب‌های درسی",
    description: "عنوان‌های کاتالوگ با کد رسمی اختیاری، گونهٔ مخاطب، وضعیت آزمایشی/منطقه‌ای و آرشیو.",
    columns: [
      { name: "title_fa", label: "عنوان", kind: "title" },
      { name: "grade_title", label: "پایه" },
      { name: "subject_title", label: "درس" },
      { name: "textbook_kind", label: "نوع" },
      { name: "audience_variant", label: "گونهٔ مخاطب" },
      { name: "implementation_status", label: "وضعیت اجرا" },
      { name: "validity_status", label: "اعتبار" },
      { name: "edition_count", label: "نسخه‌ها" },
      { name: "national_code", label: "کد رسمی" },
    ],
    fields: [
      { name: "title_fa", label: "عنوان فارسی", type: "text", required: true },
      { name: "title_en", label: "عنوان انگلیسی", type: "text" },
      { name: "grade_id", label: "پایه (خالی = پایهٔ راستی‌آزمایی‌نشده)", type: "select", from: "grades" },
      { name: "subject_id", label: "درس مرتبط", type: "select", from: "subjects" },
      { name: "academic_year_id", label: "سال تحصیلی", type: "select", from: "academic-years" },
      { name: "national_code", label: "کد رسمی (فقط واقعی — هرگز ساختگی)", type: "text" },
      { name: "textbook_kind", label: "نوع کتاب", type: "select", options: KIND_OPTIONS },
      { name: "audience_variant", label: "گونهٔ مخاطب", type: "select", options: AUDIENCE_OPTIONS },
      { name: "implementation_status", label: "وضعیت اجرا", type: "select", options: [
        { value: "confirmed", label: "قطعی" },
        { value: "experimental", label: "اجرای آزمایشی" },
        { value: "regional_pilot", label: "اجرای منطقه‌ای" },
        { value: "needs_verification", label: "نیازمند بررسی" },
      ] },
      { name: "geographic_scope", label: "محدودهٔ جغرافیایی", type: "select", options: [
        { value: "national", label: "سراسری" },
        { value: "provincial", label: "استانی" },
        { value: "school_specific", label: "مدارس خاص" },
      ] },
      { name: "validity_status", label: "اعتبار", type: "select", options: VALIDITY_OPTIONS },
      { name: "alternative_group", label: "گروه جایگزین", type: "text" },
      { name: "source_url", label: "لینک منبع رسمی", type: "text" },
      { name: "verification_note", label: "یادداشت راستی‌آزمایی", type: "textarea", hideInTable: true },
    ],
    filters: [
      { name: "grade_id", label: "پایه", from: "grades" },
      { name: "subject_id", label: "درس", from: "subjects" },
      { name: "academic_year_id", label: "سال تحصیلی", from: "academic-years" },
      { name: "audience_variant", label: "گونهٔ مخاطب", options: AUDIENCE_OPTIONS },
      { name: "implementation_status", label: "وضعیت اجرا", options: [
        { value: "confirmed", label: "قطعی" },
        { value: "experimental", label: "اجرای آزمایشی" },
        { value: "regional_pilot", label: "اجرای منطقه‌ای" },
        { value: "needs_verification", label: "نیازمند بررسی" },
      ] },
      { name: "validity_status", label: "اعتبار", options: VALIDITY_OPTIONS },
    ],
    sortable: ["id", "title_fa", "grade_id"],
    canArchive: true,
  },
  links: {
    entity: "links",
    title: "مدیریت ارتباط کتاب‌ها با پایه‌ها و رشته‌ها",
    description: "یک کتاب، چند ارتباط آموزشی — بدون ساخت رکورد تکراری کتاب.",
    columns: [
      { name: "textbook_title", label: "کتاب", kind: "title" },
      { name: "grade_title", label: "پایه" },
      { name: "branch_title", label: "شاخه" },
      { name: "field_title", label: "رشته" },
      { name: "academic_year_code", label: "سال" },
      { name: "is_mandatory", label: "اجباری", kind: "bool" },
    ],
    fields: [
      { name: "textbook_id", label: "کتاب کاتالوگ", type: "select", from: "textbooks", required: true },
      { name: "academic_year_id", label: "سال تحصیلی", type: "select", from: "academic-years", required: true },
      { name: "grade_id", label: "پایه", type: "select", from: "grades" },
      { name: "branch_id", label: "شاخه", type: "select", from: "branches" },
      { name: "field_of_study_id", label: "رشته", type: "select", from: "fields" },
      { name: "is_mandatory", label: "اجباری", type: "bool" },
      { name: "note", label: "یادداشت", type: "text", hideInTable: true },
    ],
    filters: [
      { name: "textbook_id", label: "کتاب", from: "textbooks" },
      { name: "academic_year_id", label: "سال تحصیلی", from: "academic-years" },
      { name: "grade_id", label: "پایه", from: "grades" },
      { name: "branch_id", label: "شاخه", from: "branches" },
      { name: "field_of_study_id", label: "رشته", from: "fields" },
    ],
    sortable: ["id", "textbook_id"],
    canArchive: false,
  },
  "academic-years": {
    entity: "academic-years",
    title: "مدیریت سال‌های تحصیلی",
    description: "تعریف سال جدید، کپی اولیهٔ ساختار از سال قبل بدون تخریب سال قبل.",
    columns: [
      { name: "code", label: "کد" },
      { name: "title", label: "عنوان", kind: "title" },
      { name: "is_active", label: "فعال", kind: "bool" },
    ],
    fields: [
      { name: "code", label: "کد (مثل 1406-1407)", type: "text", required: true },
      { name: "title", label: "عنوان", type: "text", required: true },
      { name: "is_active", label: "فعال", type: "bool" },
    ],
    filters: [],
    sortable: ["id", "code"],
    canArchive: false,
    supportsYearCopy: true,
  },
  editions: {
    entity: "editions",
    title: "مدیریت نسخه‌های کتاب",
    description: "نسخه‌های واقعی (PDF) — هویت مستقل از عنوان کاتالوگ؛ انتشار فقط با خط پردازش.",
    columns: [
      { name: "title", label: "عنوان نسخه", kind: "title" },
      { name: "grade_title", label: "پایه" },
      { name: "academic_year_code", label: "سال" },
      { name: "edition_label", label: "ویرایش" },
      { name: "status", label: "وضعیت" },
      { name: "has_pdf", label: "PDF", kind: "bool" },
    ],
    fields: [
      { name: "title", label: "عنوان نسخه", type: "text", required: true },
      { name: "grade_id", label: "پایه", type: "select", from: "grades", required: true },
      { name: "catalog_textbook_id", label: "عنوان کاتالوگ مرتبط", type: "select", from: "textbooks" },
      { name: "academic_year_id", label: "سال تحصیلی", type: "select", from: "academic-years" },
      { name: "edition_label", label: "شمارهٔ ویرایش", type: "text" },
      { name: "print_year", label: "سال چاپ", type: "number" },
      { name: "publisher", label: "ناشر", type: "text" },
      { name: "official_source_url", label: "منبع رسمی", type: "text" },
    ],
    filters: [
      { name: "grade_id", label: "پایه", from: "grades" },
      { name: "academic_year_id", label: "سال تحصیلی", from: "academic-years" },
    ],
    sortable: ["id", "title", "grade_id"],
    canArchive: false,
    supportsPdfUpload: true,
  },
  "program-availability": {
    entity: "program-availability",
    title: "مدیریت وضعیت اعتبار رشته‌ها",
    description: "وضعیت رسمی هر رشته به‌ازای سال تحصیلی — مستقل از انتخاب دانش‌آموز.",
    columns: [
      { name: "field_title", label: "رشته", kind: "title" },
      { name: "academic_year_code", label: "سال" },
      { name: "validity_status", label: "وضعیت اعتبار" },
      { name: "valid_from_year", label: "از سال" },
      { name: "valid_to_year", label: "تا سال" },
    ],
    fields: [
      { name: "field_of_study_id", label: "رشته", type: "select", from: "fields", required: true },
      { name: "academic_year_id", label: "سال تحصیلی", type: "select", from: "academic-years", required: true },
      { name: "validity_status", label: "وضعیت اعتبار", type: "select", options: VALIDITY_OPTIONS, required: true },
      { name: "valid_from_year", label: "شروع اعتبار (کد سال)", type: "text" },
      { name: "valid_to_year", label: "پایان اعتبار (کد سال)", type: "text" },
      { name: "evidence_note", label: "سند/بخشنامه و توضیح", type: "textarea" },
    ],
    filters: [
      { name: "academic_year_id", label: "سال تحصیلی", from: "academic-years" },
      { name: "field_of_study_id", label: "رشته", from: "fields" },
      ...VALIDITY_FILTERS,
    ],
    sortable: ["id", "field_of_study_id"],
    canArchive: false,
  },
};

/** Derived views over the same entity — the 14 requested modules. */
export const ADMIN_CATALOG_VIEWS: Record<string, AdminCatalogEntityConfig & { baseEntity: string; presetFilters: Record<string, string> }> = {
  audiences: {
    ...(ADMIN_CATALOG_ENTITIES.textbooks as AdminCatalogEntityConfig),
    entity: "audiences",
    baseEntity: "textbooks",
    presetFilters: { audience_variant: "general" },
    title: "مدیریت گونه‌های کتاب و مخاطبان",
    description: "گونه‌های عمومی، دختران/پسران و اقلیت‌های دینی — هر گونه رکورد مستقل خودش را دارد.",
  },
  special: {
    ...(ADMIN_CATALOG_ENTITIES.textbooks as AdminCatalogEntityConfig),
    entity: "special",
    baseEntity: "textbooks",
    presetFilters: {},
    title: "مدیریت کتاب‌های آزمایشی و منطقه‌ای",
    description: "کتاب‌های اجرای آزمایشی، منطقه‌ای و نیازمند بررسی — بدون انتشار سراسری.",
  },
};

export const ADMIN_CATALOG_MODULES: { href: string; title: string; kind: string }[] = [
  { href: "/admin/education/cycles", title: "مدیریت دوره‌های تحصیلی", kind: "cycles" },
  { href: "/admin/education/grades", title: "مدیریت پایه‌ها و کلاس‌ها", kind: "grades" },
  { href: "/admin/education/branches", title: "مدیریت شاخه‌ها", kind: "branches" },
  { href: "/admin/education/grounds", title: "مدیریت زمینه‌ها", kind: "grounds" },
  { href: "/admin/education/programs", title: "مدیریت رشته‌ها", kind: "fields" },
  { href: "/admin/education/subjects", title: "مدیریت درس‌ها و مواد درسی", kind: "subjects" },
  { href: "/admin/education/textbooks", title: "مدیریت کتاب‌های درسی", kind: "textbooks" },
  { href: "/admin/education/editions", title: "مدیریت نسخه‌های کتاب", kind: "editions" },
  { href: "/admin/education/links", title: "مدیریت ارتباط کتاب‌ها با پایه‌ها و رشته‌ها", kind: "links" },
  { href: "/admin/education/years", title: "مدیریت سال‌های تحصیلی", kind: "academic-years" },
  { href: "/admin/education/validity", title: "مدیریت وضعیت اعتبار رشته‌ها", kind: "program-availability" },
  { href: "/admin/education/audiences", title: "مدیریت گونه‌های کتاب و مخاطبان", kind: "audiences" },
  { href: "/admin/education/special", title: "مدیریت کتاب‌های آزمایشی و منطقه‌ای", kind: "special" },
  { href: "/admin/education/archive", title: "آرشیو اطلاعات حذف‌شده یا غیرفعال", kind: "archive" },
];
