"use client";

import { useEffect, useRef, useState } from "react";
import {
  Camera,
  Check,
  GraduationCap,
  LoaderCircle,
  Lock,
  Mail,
  Phone,
  Save,
  Send,
  Trash2,
  User as UserIcon,
} from "lucide-react";
import AccountAvatar from "@/components/AccountAvatar";
import AcademicProfilePicker from "@/components/AcademicProfilePicker";
import AccountShell from "@/components/AccountShell";
import { useAppContext } from "@/components/AppProvider";
import { formatDateTime } from "@/lib/i18n";
import type { StudentUser } from "@/lib/types";

function errorMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object" && "detail" in payload && typeof payload.detail === "string") {
    return payload.detail;
  }
  return fallback;
}

function initialNames(u: StudentUser): { first: string; last: string } {
  if (u.first_name || u.last_name) {
    return { first: u.first_name ?? "", last: u.last_name ?? "" };
  }
  if (u.full_name) {
    const parts = u.full_name.trim().split(/\s+/);
    return { first: parts[0] ?? "", last: parts.slice(1).join(" ") };
  }
  return { first: "", last: "" };
}

function ProfileFormBody({ user }: { user: StudentUser }) {
  const { preferences, authFetch, setUser } = useAppContext();
  const lang = preferences.general.language === "en" ? "en" : "fa";
  const tz = preferences.general.timezone || "Asia/Tehran";

  const defaults = initialNames(user);
  const [firstName, setFirstName] = useState(defaults.first);
  const [lastName, setLastName] = useState(defaults.last);
  const [email, setEmail] = useState(user.email ?? "");
  const [savingProfile, setSavingProfile] = useState(false);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [profileFeedback, setProfileFeedback] = useState("");
  const [profileError, setProfileError] = useState("");

  // Verified phone change state
  const [newPhone, setNewPhone] = useState("");
  const [phoneStep, setPhoneStep] = useState<"idle" | "verify">("idle");
  const [phoneOtp, setPhoneOtp] = useState("");
  const [phoneDemoCode, setPhoneDemoCode] = useState<string | null>(null);
  const [phoneBusy, setPhoneBusy] = useState(false);
  const [phoneFeedback, setPhoneFeedback] = useState("");
  const [phoneError, setPhoneError] = useState("");

  const avatarInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const res = await authFetch("/api/v1/account/profile");
        if (!res.ok || !active) return;
        const payload = (await res.json()) as { user?: StudentUser };
        if (payload.user && active) {
          setUser(payload.user);
        }
      } catch {
        // ignore transient refresh failure
      }
    })();
    return () => {
      active = false;
    };
  }, [authFetch, setUser]);

  const handleSaveProfile = async (event: React.FormEvent) => {
    event.preventDefault();
    setProfileError("");
    setProfileFeedback("");
    setSavingProfile(true);
    try {
      const res = await authFetch("/api/v1/account/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          first_name: firstName.trim() || null,
          last_name: lastName.trim() || null,
          email: email.trim() || null,
        }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          errorMessage(
            payload,
            lang === "en" ? "Failed to update profile." : "به‌روزرسانی پروفایل انجام نشد."
          )
        );
      }
      if (payload.user) setUser(payload.user as StudentUser);
      setProfileFeedback(
        lang === "en" ? "Profile saved." : "اطلاعات پروفایل با موفقیت ذخیره شد."
      );
    } catch (err) {
      setProfileError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Profile update error."
          : "خطا در ذخیره پروفایل"
      );
    } finally {
      setSavingProfile(false);
    }
  };

  const handleAvatarSelected = async (file: File) => {
    setProfileError("");
    setProfileFeedback("");
    setAvatarBusy(true);
    try {
      const form = new FormData();
      form.append("avatar", file);
      const res = await authFetch("/api/v1/account/profile/avatar", {
        method: "POST",
        body: form,
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          errorMessage(
            payload,
            lang === "en" ? "Failed to upload avatar." : "بارگذاری تصویر پروفایل انجام نشد."
          )
        );
      }
      if (payload.user) setUser(payload.user as StudentUser);
      setProfileFeedback(
        lang === "en" ? "Profile avatar updated." : "تصویر پروفایل به‌روزرسانی شد."
      );
    } catch (err) {
      setProfileError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Avatar upload error."
          : "خطا در بارگذاری تصویر"
      );
    } finally {
      setAvatarBusy(false);
      if (avatarInputRef.current) avatarInputRef.current.value = "";
    }
  };

  const handleDeleteAvatar = async () => {
    setProfileError("");
    setProfileFeedback("");
    setAvatarBusy(true);
    try {
      const res = await authFetch("/api/v1/account/profile/avatar", { method: "DELETE" });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          errorMessage(
            payload,
            lang === "en" ? "Failed to remove avatar." : "حذف تصویر پروفایل انجام نشد."
          )
        );
      }
      if (payload.user) setUser(payload.user as StudentUser);
      setProfileFeedback(
        lang === "en" ? "Profile avatar removed." : "تصویر پروفایل حذف شد."
      );
    } catch (err) {
      setProfileError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Error removing avatar."
          : "خطا در حذف تصویر"
      );
    } finally {
      setAvatarBusy(false);
    }
  };

  const handleRequestPhoneChangeOtp = async (event: React.FormEvent) => {
    event.preventDefault();
    setPhoneError("");
    setPhoneFeedback("");
    setPhoneBusy(true);
    try {
      const res = await authFetch("/api/v1/account/profile/phone/request-otp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_phone_number: newPhone.trim() }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          errorMessage(
            payload,
            lang === "en" ? "Failed to send verification code." : "ارسال کد تأیید انجام نشد."
          )
        );
      }
      setNewPhone(String(payload.phone_number ?? newPhone.trim()));
      setPhoneDemoCode(typeof payload.demo_code === "string" ? payload.demo_code : null);
      setPhoneStep("verify");
    } catch (err) {
      setPhoneError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Error sending code."
          : "خطا در ارسال کد"
      );
    } finally {
      setPhoneBusy(false);
    }
  };

  const handleVerifyPhoneChange = async (event: React.FormEvent) => {
    event.preventDefault();
    setPhoneError("");
    setPhoneFeedback("");
    setPhoneBusy(true);
    try {
      const res = await authFetch("/api/v1/account/profile/phone/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          new_phone_number: newPhone.trim(),
          code: phoneOtp.trim(),
        }),
      });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(
          errorMessage(
            payload,
            lang === "en" ? "Phone verification failed." : "تأیید شماره جدید انجام نشد."
          )
        );
      }
      if (payload.user) setUser(payload.user as StudentUser);
      setPhoneStep("idle");
      setNewPhone("");
      setPhoneOtp("");
      setPhoneDemoCode(null);
      setPhoneFeedback(
        lang === "en"
          ? "Your verified mobile number has been updated."
          : "شماره موبایل تأییدشدهٔ شما با موفقیت تغییر یافت."
      );
    } catch (err) {
      setPhoneError(
        err instanceof Error
          ? err.message
          : lang === "en"
          ? "Verification failed."
          : "خطا در تأیید کد"
      );
    } finally {
      setPhoneBusy(false);
    }
  };

  return (
    <div className="profile-grid">
      <section className="account-card academic-profile-card">
        <div className="account-card-head">
          <h2>
            <GraduationCap size={16} />{" "}
            {lang === "en" ? "Academic Placement" : "پایه و رشتهٔ تحصیلی"}
          </h2>
        </div>
        <p className="phone-change-note">
          {lang === "en"
            ? "You choose and change your grade, track, ground, and program yourself — no approval step. The tutor and retrieval scope follow this placement from your next request."
            : "انتخاب و تغییر پایه، شاخه، زمینه و رشته فقط با خودِ توست و هیچ مرحلهٔ تأییدی ندارد. معلم خصوصی و محدودهٔ بازیابی از درخواست بعدی همین انتخاب را به کار می‌برند."}
        </p>
        <AcademicProfilePicker />
      </section>

      <section className="account-card">
        <div className="account-card-head">
          <h2>
            <UserIcon size={16} />{" "}
            {lang === "en" ? "Identity & Avatar" : "هویت و تصویر پروفایل"}
          </h2>
        </div>

        <div className="profile-avatar-row">
          <AccountAvatar size={72} />
          <div className="profile-avatar-actions">
            <div className="profile-avatar-buttons">
              <button
                type="button"
                className="primary-button"
                disabled={avatarBusy}
                onClick={() => avatarInputRef.current?.click()}
              >
                {avatarBusy ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Camera size={15} />
                )}
                <span>
                  {user.avatar_url
                    ? lang === "en"
                      ? "Change Avatar"
                      : "تغییر تصویر"
                    : lang === "en"
                    ? "Upload Avatar"
                    : "بارگذاری تصویر"}
                </span>
              </button>
              {user.avatar_url && (
                <button
                  type="button"
                  className="outline-button"
                  disabled={avatarBusy}
                  onClick={() => void handleDeleteAvatar()}
                >
                  <Trash2 size={15} />
                  <span>{lang === "en" ? "Remove" : "حذف"}</span>
                </button>
              )}
            </div>
            <small>
              {lang === "en"
                ? "PNG, JPEG, or WebP up to 5 MB. Counted toward your personal storage quota."
                : "فرمت مجاز: PNG، JPEG یا WebP تا ۵ مگابایت. تصویر در سهمیهٔ فضای شخصی شما ذخیره می‌شود."}
            </small>
            <input
              ref={avatarInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void handleAvatarSelected(f);
              }}
            />
          </div>
        </div>

        <form className="account-form-stack" onSubmit={handleSaveProfile}>
          <div className="form-row">
            <label className="form-field">
              <span>{lang === "en" ? "First Name" : "نام"}</span>
              <input
                type="text"
                maxLength={80}
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                placeholder={lang === "en" ? "First name" : "مثلاً علی"}
              />
            </label>
            <label className="form-field">
              <span>{lang === "en" ? "Last Name" : "نام خانوادگی"}</span>
              <input
                type="text"
                maxLength={80}
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                placeholder={lang === "en" ? "Last name" : "مثلاً رضایی"}
              />
            </label>
          </div>

          <label className="form-field">
            <span>
              <Mail size={12} style={{ display: "inline", verticalAlign: "middle" }} />{" "}
              {lang === "en" ? "Email (optional)" : "ایمیل (اختیاری)"}
            </span>
            <input
              type="email"
              dir="ltr"
              maxLength={255}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="student@example.com"
            />
          </label>

          {profileFeedback && (
            <div className="success-note">
              <Check size={16} />
              <span>{profileFeedback}</span>
            </div>
          )}
          {profileError && <div className="inline-error">{profileError}</div>}

          <div className="account-form-footer">
            <button type="submit" className="primary-button" disabled={savingProfile}>
              {savingProfile ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}
              <span>{lang === "en" ? "Save Changes" : "ذخیره تغییرات"}</span>
            </button>
          </div>
        </form>
      </section>

      <section className="account-card profile-side-stack">
        <div className="account-card-head">
          <h2>
            <Lock size={16} />{" "}
            {lang === "en" ? "Account & Auth Rules" : "اطلاعات ثابت و احراز هویت"}
          </h2>
        </div>

        <div className="readonly-info-list">
          <div className="readonly-info-row">
            <span>{lang === "en" ? "Account Role" : "نقش حساب"}</span>
            <b>
              {user.role === "student" ? (lang === "en" ? "Student" : "دانش‌آموز") : user.role}
            </b>
          </div>
          <div className="readonly-info-row">
            <span>{lang === "en" ? "Current Plan" : "پلن فعال"}</span>
            <b>{user.plan_title}</b>
          </div>
          <div className="readonly-info-row">
            <span>{lang === "en" ? "Member Since" : "تاریخ عضویت"}</span>
            <b>{formatDateTime(user.created_at, lang, tz)}</b>
          </div>
          <div className="readonly-info-row">
            <span>{lang === "en" ? "Last Login" : "آخرین ورود"}</span>
            <b>{formatDateTime(user.last_login_at, lang, tz)}</b>
          </div>
        </div>

        <div className="phone-change-box">
          <div className="phone-change-head">
            <Phone size={15} />
            <div>
              <b>{lang === "en" ? "Verified Mobile Number" : "شماره موبایل تأییدشده"}</b>
              <span dir="ltr">{user.phone_number}</span>
            </div>
          </div>
          <p className="phone-change-note">
            {lang === "en"
              ? "Phone numbers govern authentication and cannot be modified without verifying a fresh SMS OTP sent to the new number."
              : "شماره موبایل کلید اصلی احراز هویت است و تنها پس از دریافت و تأیید کد پیامکی برای شمارهٔ جدید تغییر می‌کند."}
          </p>

          {phoneStep === "idle" ? (
            <form className="account-form-stack" onSubmit={handleRequestPhoneChangeOtp}>
              <label className="form-field">
                <span>{lang === "en" ? "New Mobile Number" : "شماره موبایل جدید"}</span>
                <input
                  type="tel"
                  dir="ltr"
                  value={newPhone}
                  onChange={(e) => setNewPhone(e.target.value)}
                  placeholder="09120000000"
                  required
                />
              </label>
              {phoneFeedback && (
                <div className="success-note">
                  <Check size={16} />
                  <span>{phoneFeedback}</span>
                </div>
              )}
              {phoneError && <div className="inline-error">{phoneError}</div>}
              <button type="submit" className="outline-button" disabled={phoneBusy}>
                {phoneBusy ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />}
                <span>
                  {lang === "en" ? "Send OTP to New Number" : "ارسال کد تأیید به شماره جدید"}
                </span>
              </button>
            </form>
          ) : (
            <form className="account-form-stack" onSubmit={handleVerifyPhoneChange}>
              {phoneDemoCode && (
                <div className="demo-otp-box">
                  <div>
                    <b>{lang === "en" ? "Demo OTP" : "کد آزمایشی"}</b>
                    <span>
                      <strong dir="ltr">{phoneDemoCode}</strong>
                    </span>
                  </div>
                  <button
                    type="button"
                    className="outline-button"
                    onClick={() => setPhoneOtp(phoneDemoCode)}
                  >
                    {lang === "en" ? "Fill" : "درج"}
                  </button>
                </div>
              )}
              <label className="form-field">
                <span>
                  {lang === "en"
                    ? `Enter 6-digit OTP for ${newPhone}`
                    : `کد ۶ رقمی ارسال‌شده به ${newPhone}`}
                </span>
                <input
                  type="text"
                  inputMode="numeric"
                  dir="ltr"
                  maxLength={6}
                  value={phoneOtp}
                  onChange={(e) => setPhoneOtp(e.target.value)}
                  placeholder="123456"
                  required
                />
              </label>
              {phoneError && <div className="inline-error">{phoneError}</div>}
              <div className="dialog-actions-row">
                <button
                  type="button"
                  className="outline-button"
                  disabled={phoneBusy}
                  onClick={() => {
                    setPhoneStep("idle");
                    setPhoneOtp("");
                    setPhoneError("");
                  }}
                >
                  {lang === "en" ? "Cancel" : "انصراف"}
                </button>
                <button type="submit" className="primary-button" disabled={phoneBusy}>
                  {phoneBusy ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />}
                  <span>{lang === "en" ? "Confirm Change" : "تأیید و تغییر شماره"}</span>
                </button>
              </div>
            </form>
          )}
        </div>
      </section>
    </div>
  );
}

export default function ProfilePage() {
  const { user, preferences } = useAppContext();
  const lang = preferences.general.language === "en" ? "en" : "fa";

  return (
    <AccountShell
      title={lang === "en" ? "Profile" : "پروفایل کاربری"}
      subtitle={
        lang === "en"
          ? "Update your personal details, avatar, and verified mobile number."
          : "اطلاعات هویتی، تصویر پروفایل و شماره موبایل تأییدشدهٔ خود را مدیریت کنید."
      }
      requireAuth
    >
      {user && <ProfileFormBody key={user.id} user={user} />}
    </AccountShell>
  );
}
