import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

const nextConfig: NextConfig = {
  // Keep Turbopack inside this app when an unrelated parent lockfile exists.
  turbopack: { root: __dirname },
};

export default withNextIntl(nextConfig);
