import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SUNIL — ops dashboard",
  description: "Watch and govern SUNIL: approvals, activity, tasks, projects and audit.",
};

/**
 * Dark-only, committed (Amendment A). The theme is painted explicitly on
 * `html`/`body` in globals.css — there is no `prefers-color-scheme` query and
 * no light map anywhere in this app, so there is nothing to drift out of sync.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* next/font would fetch the faces at build time; a stylesheet link keeps
            `pnpm build` working without network access, and the app is a single
            client shell so the "single page" caveat does not apply. */}
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="font-body antialiased">{children}</body>
    </html>
  );
}
