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
              <Link href="/departments">部门与群</Link>
              <Link href="/employees">员工</Link>
              <Link href="/agents">岗位配置</Link>
              <Link href="/models">模型中心</Link>
              <Link href="/worklogs">工作记录</Link>
              <Link href="/audit">工具审计</Link>
              <Link href="/workflows">工作流看板</Link>
            </nav>
            <div className="meta">
              员工入职 / Prompt OS / 模型中心 / 每日台账 / Skill·MCP 审计
            </div>
          </aside>
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
