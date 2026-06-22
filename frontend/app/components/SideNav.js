"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/upload", label: "Upload" },
  { href: "/reviews", label: "Reviews" },
];

export default function SideNav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  function isActive(href) {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  }

  return (
    <>
      <button
        type="button"
        className="hamburger"
        aria-label="Open menu"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <span />
        <span />
        <span />
      </button>

      {open && <div className="drawer-overlay" onClick={() => setOpen(false)} />}

      <aside className={`drawer ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="drawer-head">
          <span className="brand">SourceMind</span>
          <button type="button" className="drawer-close" aria-label="Close menu" onClick={() => setOpen(false)}>
            ×
          </button>
        </div>
        <nav className="drawer-nav">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={isActive(l.href) ? "active" : ""}
              onClick={() => setOpen(false)}
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </aside>
    </>
  );
}
