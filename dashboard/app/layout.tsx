import type { Metadata } from "next";
import { Nav } from "@/components/Nav";
import "./globals.css";
import "./dashboard.css";

export const metadata: Metadata = {
  title: "Anvil — Control Plane",
  description: "Private dashboard for the autonomous AI software company.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        {children}
      </body>
    </html>
  );
}
