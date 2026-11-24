import type { Metadata } from "next";
import { AdminObservabilityBody } from "@/components/AdminPhase1Panels";

export const metadata: Metadata = {
  title: "مرکز شفافیت | درسیار",
  robots: { index: false, follow: false },
};

export default function AdminObservabilityPage() {
  return <AdminObservabilityBody />;
}
