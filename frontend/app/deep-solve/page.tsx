"use client";

import AccountShell from "@/components/AccountShell";
import DeepSolveWorkspace from "@/components/DeepSolveWorkspace";

export default function DeepSolvePage() {
  return (
    <AccountShell title="حل گام‌به‌گام" subtitle="راهنمای مرحله‌به‌مرحله؛ پاسخ نهایی فقط در پایان یا با درخواست پاسخ کامل نمایش داده می‌شود.">
      <DeepSolveWorkspace />
    </AccountShell>
  );
}
