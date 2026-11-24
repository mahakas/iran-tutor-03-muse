import type { Metadata } from "next";
import ImmersiveReaderPage from "@/components/ImmersiveReaderPage";

export const metadata: Metadata = {
  title: "مطالعهٔ غوطه‌ور | درسیار",
  robots: { index: false, follow: false },
};

export default async function StudyPage({
  params,
  searchParams,
}: {
  params: Promise<{ bookId: string }>;
  searchParams?: Promise<{ page?: string }>;
}) {
  const { bookId } = await params;
  const resolvedSearch = (await searchParams) ?? {};
  const parsedPage = Number.parseInt(resolvedSearch.page ?? "", 10);
  const initialPageIndex =
    Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : undefined;
  return <ImmersiveReaderPage bookId={bookId} initialPageIndex={initialPageIndex} />;
}
