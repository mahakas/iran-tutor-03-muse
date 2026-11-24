"use client";

import AccountShell from "@/components/AccountShell";
import MasteryWorkspace from "@/components/MasteryWorkspace";

export default function MasteryPage() {
  return (
    <AccountShell title="مسیر تسلط" subtitle="تسلط هر فصل از نتیجهٔ آزمون، مرور فلش‌کارت و حل گام‌به‌گام محاسبه می‌شود.">
      <MasteryWorkspace />
    </AccountShell>
  );
}
