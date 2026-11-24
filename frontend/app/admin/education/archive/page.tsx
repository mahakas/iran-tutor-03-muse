import type { Metadata } from "next";
import AdminCatalogArchiveBody from "@/components/AdminCatalogArchiveBody";

export const metadata: Metadata = {
  title: "آرشیو کاتالوگ آموزشی | درسیار",
  robots: { index: false, follow: false },
};

export default function Page() {
  return <AdminCatalogArchiveBody />;
}
