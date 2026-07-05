import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { THEME_STORAGE_KEY } from "@/lib/hooks/useTheme";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "SourceMind",
  description: "Local-first course workbook generator",
};

// Runs synchronously during HTML parsing, before first paint, so the
// correct theme is applied with no flash — see
// https://nextjs.org/docs/app/guides/preventing-flash-before-hydration#themes.
// Mirrors useTheme.ts's resolution logic (system falls back to
// prefers-color-scheme); keep the two in sync if either changes.
const noFlashThemeScript = `(function(){try{var s=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});var p=(s==="light"||s==="dark"||s==="system")?s:"system";var e=p==="system"?(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):p;document.documentElement.setAttribute("data-theme",e);}catch(err){}})();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      data-theme="light"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: noFlashThemeScript }} />
      </head>
      <body className="min-h-full flex flex-col">
        <header className="border-b border-black/10 px-6 py-4 dark:border-white/10">
          <h1 className="text-lg font-semibold">SourceMind</h1>
        </header>
        <main className="flex flex-1 flex-col">{children}</main>
      </body>
    </html>
  );
}
