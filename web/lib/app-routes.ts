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
  // One header tab for the whole administrative area; everything under /admin/ is a
  // sub-tab of it (see `components/app/admin-nav.tsx`), which is why these are
  // `nav: false`. They stay in this list because the command palette searches it —
  // being off the header should not make a page unreachable by name.
  { href: "/admin", key: "admin", min: "admin", nav: true },
  { href: "/admin/users", key: "users", min: "admin", nav: false },
  { href: "/admin/audit", key: "audit", min: "admin", nav: false },
  { href: "/admin/import", key: "import", min: "admin", nav: false },
  { href: "/admin/branding", key: "branding", min: "superadmin", nav: false },
  { href: "/admin/ai", key: "aiSettings", min: "superadmin", nav: false },
] as const satisfies readonly {
  href: string;
  key: string;
  min: Role;
  nav: boolean;
}[];
