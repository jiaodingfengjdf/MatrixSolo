import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "MatrixSolo Admin",
  description: "一人影视自媒体多 Agent 协作中台 · 管理台",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=Syne:wght@600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <div className="app-shell">
          <aside className="sidebar">
            <div className="brand">
              Matrix<span>Solo</span>
            </div>
            <nav className="nav">
              <Link href="/">系统总览</Link>
              <Link href="/workflows">工作流看板</Link>
              <Link href="/agents">岗位 Agent</Link>
            </nav>
            <div className="meta">身份 / Prompt / LLM / Skills / MCP</div>
          </aside>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
