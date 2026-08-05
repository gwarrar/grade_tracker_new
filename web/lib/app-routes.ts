import type { Role } from "@/lib/session";

// Only routes that exist. A nav that lists /reports before /reports is built is a
// link straight to a 404 — worse than the feature being absent, because it reads
// as broken rather than as not-yet-there. Restored as each page lands.
export const APP_ROUTES = [
  { href: "/dashboard", key: "dashboard", min: "student", nav: true },
  { href: "/students", key: "students", min: "student", nav: true },
  { href: "/courses", key: "courses", min: "student", nav: true },
  { href: "/grades", key: "grades", min: "student", nav: true },
  { href: "/reports", key: "reports", min: "teacher", nav: true },
  { href: "/profile", key: "profile", min: "student", nav: false },
  { href: "/admin/users", key: "admin", min: "admin", nav: true },
  { href: "/admin/audit", key: "audit", min: "admin", nav: true },
  { href: "/admin/import", key: "import", min: "admin", nav: true },
  { href: "/admin/branding", key: "branding", min: "superadmin", nav: true },
  { href: "/admin/ai", key: "aiSettings", min: "superadmin", nav: false },
] as const satisfies readonly {
  href: string;
  key: string;
  min: Role;
  nav: boolean;
}[];
