import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

import AppShell from "@/components/AppShell";
import SiteHeader from "@/components/SiteHeader";
import SkipToMainLink from "@/components/SkipToMainLink";
import { THEME_BOOTSTRAP_SCRIPT } from "@/lib/theme/bootstrap";

// Organic design system faces, vendored so production builds and page loads
// never depend on Google Fonts network availability.
const caprasimo = localFont({
  src: "./fonts/caprasimo-latin-400.woff2",
  weight: "400",
  style: "normal",
  variable: "--font-caprasimo",
  display: "swap",
});

const figtree = localFont({
  src: "./fonts/figtree-latin-variable.woff2",
  weight: "300 900",
  style: "normal",
  variable: "--font-figtree",
  display: "swap",
});

const geistMono = localFont({
  src: "./fonts/geist-mono-latin-variable.woff2",
  weight: "100 900",
  style: "normal",
  variable: "--font-geist-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "SourceMind",
  description: "Local-first course workbook generator",
};

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
      className={`${caprasimo.variable} ${figtree.variable} ${geistMono.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
      </head>
      <body className="h-full">
        <SkipToMainLink />
        <AppShell header={<SiteHeader />}>{children}</AppShell>
      </body>
    </html>
  );
}
