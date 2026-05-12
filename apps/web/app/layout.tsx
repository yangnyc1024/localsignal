import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LocalSignal",
  description: "AI-powered local change intelligence."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
