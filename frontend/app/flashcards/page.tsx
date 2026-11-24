"use client";

import AccountShell from "@/components/AccountShell";
import FlashcardsWorkspace from "@/components/FlashcardsWorkspace";

export default function FlashcardsPage() {
  return (
    <AccountShell
      title="فلش‌کارت‌های هوشمند"
      subtitle="کارت‌های مستند به کتاب درسی، مرور با الگوریتم SM-2 و خروجی Anki."
    >
      <FlashcardsWorkspace />
    </AccountShell>
  );
}
