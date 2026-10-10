"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 font-semibold tracking-tight ${className}`}>
      <svg viewBox="0 0 32 32" className="h-6 w-6" aria-hidden>
        <rect x="1" y="1" width="30" height="30" rx="8" fill="currentColor" opacity="0.12" />
        {/* viewfinder corners: first-person footage */}
        <path d="M7 12V8.5A1.5 1.5 0 0 1 8.5 7H12M20 7h3.5A1.5 1.5 0 0 1 25 8.5V12M25 20v3.5a1.5 1.5 0 0 1-1.5 1.5H20M12 25H8.5A1.5 1.5 0 0 1 7 23.5V20"
          fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        <path d="M11.5 16.5l3 3 6-7" fill="none" stroke="var(--accent)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      SoloSim
    </span>
  );
}

const LINKS = [
  { href: "/queue", label: "Review queue" },
  { href: "/bench", label: "Evidence" },
];

export function AppHeader({ children }: { children?: React.ReactNode }) {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-4 px-4">
        <Link href="/" className="flex shrink-0 items-center gap-2" aria-label="SoloSim home">
          <Logo />
          <span className="hidden rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted sm:inline">pre-QA for first-person data</span>
        </Link>
        <div className="min-w-0 flex-1">{children}</div>
        <nav aria-label="Main" className="flex shrink-0 items-center gap-1 text-sm">
          {LINKS.map((l) => {
            const on = path === l.href || path.startsWith(l.href + "/") || (l.href === "/queue" && path.startsWith("/review"));
            return (
              <Link key={l.href} href={l.href} aria-current={on ? "page" : undefined}
                className={`whitespace-nowrap rounded-md px-2.5 py-1.5 transition ${on ? "bg-surface-2 text-ink" : "text-muted hover:text-ink"}`}>
                {l.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
