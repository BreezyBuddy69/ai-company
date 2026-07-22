"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/agents", label: "Agents" },
  { href: "/opportunities", label: "Opportunities" },
  { href: "/evolution", label: "Evolution" },
  { href: "/logs", label: "Logs" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav className="nav">
      <span className="nav-brand">AI Software Factory</span>
      {LINKS.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className={`nav-link ${pathname === link.href ? "active" : ""}`}
        >
          {link.label}
        </Link>
      ))}
    </nav>
  );
}
