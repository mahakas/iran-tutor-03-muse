"use client";

import AccountShell from "@/components/AccountShell";
import MistakeBankWorkspace from "@/components/MistakeBankWorkspace";

export default function MistakesPage() {
  return (
    <AccountShell title="بانک اشتباهات" subtitle="سؤال‌های غلط یا رد‌شده در آزمون‌ها؛ دوباره تمرین کنید یا به فلش‌کارت بفرستید.">
      <MistakeBankWorkspace />
    </AccountShell>
  );
}
