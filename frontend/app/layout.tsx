import React from 'react';
import './globals.css';
import Link from 'next/link';
import { Activity, Database } from 'lucide-react';

export const metadata = {
  title: 'HFT Dashboard | Deriv',
  description: 'Motor de Inteligência Estatística (HFT Varejo)',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR">
      <head>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
      </head>
      <body className="font-sans bg-dark-bg text-dark-text min-h-screen selection:bg-dark-accent/30 selection:text-white">
        {/* Navigation */}
        <nav className="sticky top-0 z-50 border-b border-dark-border bg-dark-bg/90 backdrop-blur-sm">
          <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center gap-6">
            <span className="text-xs font-black tracking-[0.3em] text-dark-accent uppercase">DERIV · HFT</span>
            <div className="flex items-center gap-1">
              <Link
                href="/"
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm text-dark-text hover:text-white hover:bg-dark-card transition-all duration-150"
              >
                <Activity className="w-3.5 h-3.5" />
                Dashboard
              </Link>
              <Link
                href="/intelligence"
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm text-dark-text hover:text-white hover:bg-dark-card transition-all duration-150"
              >
                <Database className="w-3.5 h-3.5" />
                Intelligence
              </Link>
            </div>
          </div>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}

