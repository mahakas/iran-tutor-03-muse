"use client";

import AccountShell from "@/components/AccountShell";
import PodcastWorkspace from "@/components/PodcastWorkspace";

export default function PodcastPage() {
  return (
    <AccountShell
      title="پادکست آموزشی"
      subtitle="گفت‌وگوی صوتی تولیدشده از فصل کتاب درسی — مثل یک معلم و هم‌صحبت که برایتان درس می‌گویند."
    >
      <PodcastWorkspace />
    </AccountShell>
  );
}
