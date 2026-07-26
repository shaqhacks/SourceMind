"use client";

import Link from "next/link";
import { Menu } from "lucide-react";

import DueBadge from "@/components/DueBadge";
import ThemeToggle from "@/components/ThemeToggle";
import { useSidebarCollapsed } from "@/lib/hooks/useSidebarCollapsed";

/**
 * App header (redesign handoff "App Shell"): sidebar toggle, brand in the
 * display face, due tag + theme toggle + avatar placeholder on the right.
 * Extracted out of app/layout.tsx so it's unit-testable on its own — RTL
 * can't cleanly mount RootLayout's own <html>/<head>/next/font wrapper.
 * Brand is a <p>, not a heading: pages own their h1.
 */
export default function SiteHeader() {
  const { collapsed, toggle } = useSidebarCollapsed();

  return (
    <header className="flex items-center gap-3 border-b border-divider px-5 py-3">
      <button
        type="button"
        onClick={toggle}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        aria-expanded={!collapsed}
        className="flex h-9 w-9 items-center justify-center rounded-md transition-colors hover:bg-foreground/[0.07]"
      >
        <Menu aria-hidden="true" className="h-5 w-5" strokeWidth={2.75} />
      </button>
      <p className="font-heading text-xl leading-none text-accent">
        <Link href="/">SourceMind</Link>
      </p>
      <div className="ml-auto flex items-center gap-3">
        <DueBadge />
        <ThemeToggle />
        {/* Decorative avatar per the mock — single-user app, no account. */}
        <span
          aria-hidden="true"
          className="flex h-[34px] w-[34px] items-center justify-center rounded-full bg-sage-300 text-xs font-semibold text-sage-900"
        >
          S
        </span>
      </div>
    </header>
  );
}
