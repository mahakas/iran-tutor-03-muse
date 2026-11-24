import type { Metadata } from "next";
import "@fontsource/vazirmatn/arabic-400.css";
import "@fontsource/vazirmatn/arabic-500.css";
import "@fontsource/vazirmatn/arabic-700.css";
import "katex/dist/katex.min.css";
import AppProvider from "@/components/AppProvider";
import PodcastPlayerProvider from "@/components/PodcastPlayerProvider";
import ToastHost from "@/components/ToastHost";
import "./globals.css";

export const metadata: Metadata = {
  title: "درسیار | معلم خصوصی هوشمند",
  description: "یادگیری دقیق و مستند بر اساس کتاب‌های درسی ایران",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="fa" dir="rtl">
      <body>
        <AppProvider>
          <PodcastPlayerProvider>
            {children}
            <ToastHost />
          </PodcastPlayerProvider>
        </AppProvider>
      </body>
    </html>
  );
}
