import type { Metadata, Viewport } from "next";
import "@fontsource/ibm-plex-sans-thai/400.css";
import "@fontsource/ibm-plex-sans-thai/500.css";
import "@fontsource/ibm-plex-sans-thai/600.css";
import "./globals.css";
import {PwaBoot} from "@/components/pwa";
export const metadata: Metadata = {
  title: "Smart Finance · การเงินของคุณ",
  description: "พื้นที่ส่วนตัวสำหรับดูแลรายรับรายจ่าย",
  manifest: "/manifest.webmanifest",
};
export const viewport: Viewport = {
  themeColor: "#F6F7F3",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th" className="light">
      <body>{children}<PwaBoot/></body>
    </html>
  );
}
