import type { Metadata } from "next";
import { AdminProvidersBody } from "@/components/AdminPhase1Panels";

export const metadata: Metadata = {
  title: "ارائه‌دهنده‌ها و مسیر مدل | درسیار",
  robots: { index: false, follow: false },
};

export default function AdminProvidersPage() {
  return <AdminProvidersBody />;
}
