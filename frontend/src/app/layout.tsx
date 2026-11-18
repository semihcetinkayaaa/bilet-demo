import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { BRAND, CATEGORIES } from "@/lib/format";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin", "latin-ext"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: `${BRAND} | Konser, maç, sinema ve tiyatro biletleri`, template: `%s | ${BRAND}` },
  description: "Konser, maç, sinema ve tiyatro biletleri. Demo bilet satış sitesi.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="tr" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <div className="bg-amber-100 text-amber-900 text-center text-xs py-1.5 px-4 dark:bg-amber-900/40 dark:text-amber-100">
          Demo site: ödemeler gerçek değildir, gerçek kart bilgisi girmeyin.
        </div>
        <header className="border-b border-black/10 dark:border-white/10">
          <nav className="mx-auto max-w-6xl px-4 h-16 flex items-center gap-6">
            <Link href="/" className="font-bold text-lg tracking-tight">
              <span className="text-brand">●</span> {BRAND}
            </Link>
            <ul className="hidden sm:flex gap-4 text-sm text-muted">
              {CATEGORIES.map((c) => (
                <li key={c.value}>
                  <Link href={`/?kategori=${c.value}`} className="hover:text-foreground">
                    {c.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="border-t border-black/10 dark:border-white/10 py-8 text-center text-sm text-muted">
          © {BRAND}. Bu bir demo projesidir; etkinlikler, mekanlar ve kişiler hayalidir.
        </footer>
      </body>
    </html>
  );
}
