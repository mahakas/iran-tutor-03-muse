import type { Metadata } from "next";
import AdminUserDetailBody from "@/components/AdminUserDetailBody";

export const metadata: Metadata = {
  title: "پروندهٔ کاربر | درسیار",
  robots: { index: false, follow: false },
};

export default async function AdminUserDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AdminUserDetailBody userId={id} />;
}
