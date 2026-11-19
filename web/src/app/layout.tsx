import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Motion review",
  description: "Play an audited GLB and see where and when the motion breaks.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
