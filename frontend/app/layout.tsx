import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Workspace Agent",
  description: "Personal workspace agent for files, Drive, Gmail, and chat"
};

export default function RootLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
