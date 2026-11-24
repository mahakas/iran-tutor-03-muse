"use client";

import AccountShell from "@/components/AccountShell";
import LivingBookWorkspace from "@/components/LivingBookWorkspace";

export default function LivingBookPage() {
  return (
    <AccountShell title="کتاب زنده فصل" subtitle="مفاهیم، نکته‌ها، نمودار، آزمون و فلش‌کارت‌های یک فصل، همه با شمارهٔ صفحهٔ چاپی.">
      <LivingBookWorkspace />
    </AccountShell>
  );
}
