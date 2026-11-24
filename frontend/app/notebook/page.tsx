"use client";

import AccountShell from "@/components/AccountShell";
import NotebookWorkspace from "@/components/NotebookWorkspace";

export default function NotebookPage() {
  return (
    <AccountShell title="دفترچهٔ یادداشت" subtitle="یادداشت‌های متنی و نمودار؛ پیشنهادهای هوشمند فقط با تأیید شما و بر اساس متن کتاب اعمال می‌شوند.">
      <NotebookWorkspace />
    </AccountShell>
  );
}
