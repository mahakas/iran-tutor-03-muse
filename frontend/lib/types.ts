export type TutorMode = "tutor" | "problem_solver" | "question_designer";

export type AppLanguage = "fa" | "en";
export type VisualStyle = "standard" | "modern" | "compact";
export type ColorMode = "light" | "dark" | "system";
export type ReduceMotionMode = "off" | "on" | "system";
export type FontFamilyChoice = "vazir" | "system" | "sahel" | "mono";
export type ThemePresetId =
  | "darsyar"
  | "emerald"
  | "slate"
  | "ocean"
  | "warm"
  | "violet"
  | "graphite"
  | "midnight";

export type AppearanceModePalette = {
  theme: ThemePresetId;
  accent: string;
  background: string;
  foreground: string;
  font_family: FontFamilyChoice;
};

export type UserPreferences = {
  general: {
    language: AppLanguage;
    timezone: string;
    default_tutor_mode: TutorMode;
  };
  appearance: {
    visual_style: VisualStyle;
    color_mode: ColorMode;
    separate_mode_themes: boolean;
    light: AppearanceModePalette;
    dark: AppearanceModePalette;
    ui_font_size: number;
    code_font_size: number;
    reduce_motion: ReduceMotionMode;
    contrast: number;
    diff_markers: boolean;
  };
  notifications: {
    email_updates: boolean;
    usage_alerts: boolean;
    plan_expiry_reminders: boolean;
    exam_reminders: boolean;
    security_alerts: boolean;
  };
  privacy: {
    save_chat_history: boolean;
    store_uploaded_attachments: boolean;
    show_phone_masked: boolean;
  };
};

export type GradeOption = {
  number: number;
  title: string;
  has_major: boolean;
};

export type MajorOption = { code: string; title: string };
export type BranchOption = { code: string; title: string; min_grade: number; max_grade: number };
export type FieldOption = { code: string; title: string; branch_code: string; branch_title: string };
export type BookOption = {
  id: number;
  title: string;
  grade_number: number;
  major_code: string;
  branch_code?: string | null;
  field_code?: string | null;
  academic_year_code?: string | null;
  edition_label?: string | null;
  print_year?: number | null;
  publisher?: string | null;
  status: string;
};

export type Source = {
  book_id?: number;
  book_title?: string;
  grade_number?: number | null;
  branch_titles?: string[];
  field_titles?: string[];
  subject_titles?: string[];
  academic_year_code?: string | null;
  edition_label?: string | null;
  print_year?: number | null;
  publisher?: string | null;
  chapter_number?: number | null;
  chapter_title?: string | null;
  pdf_page_index?: number | null;
  printed_page_number?: number | null;
  citation?: string;
  score?: number;
};

export type UsageInfo = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_toman: number;
  tokens_remaining: number;
};

export type StudentUser = {
  id: string;
  phone_number: string;
  masked_phone: string;
  first_name: string | null;
  last_name: string | null;
  full_name: string | null;
  email: string | null;
  avatar_url: string | null;
  role: string;
  plan_code: "trial" | "normal" | "pro" | "vip" | string;
  plan_title: string;
  tokens_total: number;
  tokens_remaining: number;
  tokens_used_total: number;
  tokens_used_today: number;
  used_value_toman: number;
  storage_quota_bytes: number;
  plan_started_at: string | null;
  plan_expires_at: string | null;
  days_remaining: number;
  is_expired: boolean;
  is_active: boolean;
  preferences: UserPreferences;
  last_login_at: string | null;
  created_at: string | null;
};

export type PlanItem = {
  id: number;
  code: string;
  name: string;
  description: string;
  price_toman: number;
  token_quota: number;
  duration_days: number;
  storage_quota_bytes: number;
  effective_toman_per_1k: number;
  is_active: boolean;
  sort_order: number;
};

export type PublicPlansPayload = {
  plans: PlanItem[];
  token_price_per_1k_toman: number;
  starter_tokens: number;
  starter_duration_days: number;
  payment_mode: string;
};

export type TokenUsageLogItem = {
  id: string;
  action: string;
  book_id: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_toman: number;
  created_at: string | null;
};

export type PaymentTransactionItem = {
  id: string;
  plan_code: string;
  plan_name: string;
  amount_toman: number;
  tokens_granted: number;
  duration_days: number;
  provider: string;
  status: string;
  ref_id: string | null;
  created_at: string | null;
  paid_at: string | null;
};

export type StorageCategoryBreakdown = {
  bytes: number;
  count: number;
};

export type StorageSummary = {
  quota_bytes: number;
  used_bytes: number;
  remaining_bytes: number;
  over_quota: boolean;
  usage_percent: number;
  status: "normal" | "warning" | "full";
  total_files: number;
  categories: {
    images: StorageCategoryBreakdown;
    audio: StorageCategoryBreakdown;
    files: StorageCategoryBreakdown;
  };
  plan_code: string;
  plan_title: string;
};

export type UserFileDependency = {
  type: "profile_avatar" | "chat_session";
  id?: string;
  title?: string;
  label?: string;
};

export type UserFileItem = {
  id: string;
  filename: string;
  mime_type: string;
  category: "image" | "audio" | "file";
  size_bytes: number;
  source_context: string;
  chat_session_id: string | null;
  book_id: number | null;
  status: string;
  created_at: string | null;
  dependencies: UserFileDependency[];
};

export type UserFilesListResponse = {
  items: UserFileItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  storage: StorageSummary;
};

export type UserSessionItem = {
  id: string;
  user_agent: string | null;
  ip_address: string | null;
  is_current: boolean;
  is_active: boolean;
  last_seen_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string | null;
};

export type TutorResponse = {
  answer: string;
  sources: Source[];
  blocks?: unknown[];
  recognized_question?: string;
  transcript?: string;
  uncertain_parts?: string[];
  usage?: UsageInfo;
  saved_file?: UserFileItem;
};

export type ExamQuestion = {
  id: string;
  prompt: string;
  choices: Record<"A" | "B" | "C" | "D", string>;
  points: number;
  source: Source;
};

export type Exam = {
  id: string;
  title: string;
  book_id: number;
  grade_number: number;
  major_code: string;
  branch_code?: string | null;
  exam_type: "konkoor" | "final";
  time_limit_seconds: number;
  expires_at: string;
  status?: "active" | "submitted" | "expired";
  questions: ExamQuestion[];
  report_card?: ExamReport;
  submitted_answers?: Record<string, string | null>;
  usage?: UsageInfo;
};

export type ExamSummary = {
  id: string;
  title: string;
  book_id: number;
  book_title: string | null;
  grade_number: number;
  major_code: string;
  branch_code?: string | null;
  exam_type: "konkoor" | "final";
  status: "active" | "submitted" | "expired";
  question_count: number;
  time_limit_seconds: number;
  expires_at: string;
  created_at: string | null;
  submitted_at: string | null;
  report_summary: {
    score: number;
    scale: "percent" | "out_of_20";
    correct: number;
    wrong: number;
    unanswered: number;
    total_questions: number;
  } | null;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  /** Typed Learning Blocks (Phase 2) — see lib/learningBlocks.ts. */
  blocks?: unknown[];
  attachment?: string;
  /** Phase 4: streaming placeholder while the answer is still arriving. */
  pending?: boolean;
  /** Phase 4: stream that produced this answer (used for Regenerate bookkeeping). */
  streamId?: string;
  /** Phase 4: mode chosen by the Auto-Mode router (only set in Auto mode). */
  routedMode?: TutorMode;
  routerSource?: "llm" | "heuristic";
};

export type ChatSessionSummary = {
  id: string;
  title: string;
  book_id: number;
  book_title: string | null;
  grade_number: number;
  major_code: string;
  branch_code?: string | null;
  mode: TutorMode;
  message_count: number;
  created_at: string | null;
  updated_at: string | null;
};

export type ChatSessionDetail = ChatSessionSummary & {
  messages: ChatMessage[];
};

export type ExamQuestionResult = {
  id: string;
  answer: string | null;
  correct: boolean;
  correct_option: string;
  explanation: string;
  source: Source;
};

export type ExamReport = {
  score: number;
  scale: "percent" | "out_of_20";
  correct: number;
  wrong: number;
  unanswered: number;
  total_questions: number;
  by_question: ExamQuestionResult[];
};
