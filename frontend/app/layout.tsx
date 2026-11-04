import type { Metadata } from "next";
// Fonts are bundled with the app (no download at build time, so builds can't fail on a Google Fonts hiccup).
import "@fontsource-variable/newsreader";
import "@fontsource-variable/public-sans";
import "./globals.css";

export const metadata: Metadata = {
  title: "CreditLens",
  description: "Evidence-linked credit analysis: sourced financials, a trained stress screen and loan stress tests.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="demo-banner" role="note">
          Course demo, IE Master in Finance (AI in Finance). Public company filings and sample data only; not for real credit decisions.
        </div>
        {children}
      </body>
    </html>
  );
}
