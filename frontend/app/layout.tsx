import type { Metadata } from "next";
import { Newsreader, Public_Sans } from "next/font/google";
import "./globals.css";

const newsreader = Newsreader({ subsets: ["latin"], variable: "--font-newsreader", weight: ["400", "500"] });
const publicSans = Public_Sans({ subsets: ["latin"], variable: "--font-public-sans", weight: ["400", "600"] });

export const metadata: Metadata = {
  title: "CreditLens",
  description: "Evidence-linked credit analysis: sourced financials, a trained stress screen and loan stress tests.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${newsreader.variable} ${publicSans.variable}`}>
      <body>{children}</body>
    </html>
  );
}
