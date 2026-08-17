import type { Metadata } from "next";
import { JetBrains_Mono, Orbitron, Share_Tech_Mono } from "next/font/google";
import "./globals.css";

// SUNIL design-system font stacks — docs/design/DESIGN_SYSTEM.md §2.
//
// Two deliberate corrections vs. the source prototypes are carried here
// (see DESIGN_SYSTEM.md §0):
//  - Body prose (chat messages, composer, code) uses JetBrains Mono, not
//    Share Tech Mono, because Share Tech Mono ships one weight only (400,
//    no bold) and cannot render assistant markdown emphasis.
//  - Share Tech Mono is kept, but only for short HUD chrome strings
//    (labels, timestamps, badges) — one weight, never bold.
const orbitron = Orbitron({
  subsets: ["latin"],
  weight: ["400", "600", "700", "800"],
  variable: "--font-display",
  display: "swap",
});

const shareTechMono = Share_Tech_Mono({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-mono-ui",
  display: "swap",
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  variable: "--font-mono-body",
  display: "swap",
});

export const metadata: Metadata = {
  title: "S.U.N.I.L",
  description: "SUNIL — the owner's AI assistant.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${orbitron.variable} ${shareTechMono.variable} ${jetBrainsMono.variable}`}
    >
      <body className="min-h-screen bg-canvas font-mono-body text-body text-text-primary antialiased">
        {children}
      </body>
    </html>
  );
}
