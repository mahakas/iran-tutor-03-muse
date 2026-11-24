/** Podcast types shared by the student workspace and the global mini player. */

export type PodcastFormat = "deep_dive" | "brief" | "critique" | "debate";
export type PodcastLength = "short" | "standard" | "long";
export type PodcastStatus =
  | "queued"
  | "generating_script"
  | "generating_audio"
  | "assembling_audio"
  | "completed"
  | "failed"
  | "cancelled";

export const FORMAT_LABELS: Record<PodcastFormat, string> = {
  deep_dive: "گفت‌وگوی عمیق",
  brief: "پادکست کوتاه",
  critique: "نقد و بررسی",
  debate: "مناظرهٔ آموزشی",
};

export const FORMAT_HINTS: Record<PodcastFormat, string> = {
  deep_dive: "گفت‌وگوی دو نفرهٔ مدرس و دانش‌آموز کنجکاو",
  brief: "یک گوینده، چکیدهٔ نکات مهم برای مرور سریع",
  critique: "بررسی و نقد آموزشی محتوا در محدودهٔ منابع",
  debate: "مقایسهٔ دو روش یا دو مفهوم در چارچوب کتاب",
};

export const LENGTH_LABELS: Record<PodcastLength, string> = {
  short: "کوتاه",
  standard: "استاندارد",
  long: "طولانی",
};

export const STATUS_LABELS: Record<PodcastStatus, string> = {
  queued: "در صف تولید",
  generating_script: "تولید متن",
  generating_audio: "تولید صدا",
  assembling_audio: "ترکیب فایل‌ها",
  completed: "آماده",
  failed: "ناموفق",
  cancelled: "لغو شده",
};

export const PLAYBACK_SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2] as const;

export const FEEDBACK_REASON_LABELS: Record<string, string> = {
  bad_voice: "صدای نامناسب",
  bad_pronunciation: "تلفظ نامناسب",
  unclear_explanations: "توضیحات علمی نامفهوم",
  repetitive: "مطالب تکراری",
  bad_length: "طول نامناسب",
  unnatural_dialogue: "گفت‌وگوی غیرطبیعی",
  wrong_information: "اطلاعات نادرست",
};

export type PodcastSpeaker = "host_a" | "host_b" | "narrator";

export type PodcastCitation = { index: number; citation: string; kind?: string };

export type PodcastSegment = {
  id: number;
  position: number;
  speaker: PodcastSpeaker;
  speaker_label: string;
  text: string;
  source_refs: number[];
  start_time: number | null;
  end_time: number | null;
  duration_seconds: number | null;
  estimated_seconds: number;
  status: string;
};

export type PodcastQuestion = {
  id: number;
  question: string;
  answer_md: string;
  citations: { index: number; citation: string }[];
  created_at: string | null;
};

export type PodcastEpisode = {
  id: number;
  title: string;
  description: string;
  format: PodcastFormat;
  format_label: string;
  language: string;
  length: PodcastLength;
  book_id: number | null;
  book_title: string | null;
  chapters: number[];
  status: PodcastStatus;
  progress: number;
  progress_stage: string;
  error_code: string | null;
  error_detail: string | null;
  duration_seconds: number | null;
  byte_size: number | null;
  has_audio: boolean;
  single_speaker_mode: boolean;
  speakers: Record<string, string>;
  suggested_questions: string[];
  created_at: string | null;
  completed_at: string | null;
  segments?: PodcastSegment[];
  transcript?: string;
  sources?: PodcastCitation[];
  questions?: PodcastQuestion[];
  feedback?: { liked: boolean; reasons: string[] };
};

export type PodcastConfig = {
  formats: { key: PodcastFormat; label: string }[];
  languages: { code: string; label: string }[];
  lengths: { key: PodcastLength; label: string; target_minutes: string }[];
  dual_voice_available: boolean;
  single_speaker_mode: boolean;
  max_custom_prompt_chars: number;
};

export function podcastErrorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === "string") {
      return detail[0].msg as string;
    }
  }
  return fallback;
}

export function formatDuration(seconds: number | null): string {
  if (!seconds || !Number.isFinite(seconds) || seconds <= 0) return "—";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")} دقیقه`;
}

export function faDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("fa-IR");
}
