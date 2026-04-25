import type { Metadata } from "next";
import { cn } from "@/lib/utils/cn";
import "./globals.css";

export const metadata: Metadata = {
  title: "Portfolio Thesis Engine",
  description: "Institutional-grade equity research workspace.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={cn("min-h-screen bg-background font-sans antialiased")}>
        {children}
      </body>
    </html>
  );
}
