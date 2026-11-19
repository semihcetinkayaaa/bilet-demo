import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { logoutAction } from "@/app/actions";
import { getMyOrders } from "@/lib/api";
import { categoryInfo, formatDateShort, formatTL, statusLabel } from "@/lib/format";
import { getCurrentUser, getSessionToken } from "@/lib/session";

export const metadata: Metadata = { title: "Hesabım", robots: { index: false } };

export default function AccountPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <Suspense fallback={<div className="h-96 animate-pulse rounded-2xl bg-card" />}>
        <AccountContent />
      </Suspense>
    </div>
  );
}

const STATUS_STYLE: Record<string, string> = {
  paid: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-200",
  pending: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200",
  cancelled: "bg-black/5 text-muted dark:bg-white/10",
};

async function AccountContent() {
  const user = await getCurrentUser();
  if (!user) redirect("/giris?sonra=/hesabim");
  const orders = await getMyOrders((await getSessionToken())!);

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-black/10 bg-card p-6 dark:border-white/10">
        <div>
          <h1 className="text-2xl font-bold">Merhaba, {user.name.split(" ")[0]}</h1>
          <p className="mt-1 text-sm text-muted">{user.email}</p>
          <p className="mt-1 text-xs text-muted">
            Üyelik: {new Date(user.created_at).toLocaleDateString("tr-TR", { timeZone: "Europe/Istanbul" })}
          </p>
        </div>
        <form action={logoutAction}>
          <button className="rounded-lg border border-black/15 px-4 py-2 text-sm hover:border-red-500 hover:text-red-600 dark:border-white/15">
            Çıkış yap
          </button>
        </form>
      </section>

      <section>
        <h2 className="mb-4 text-lg font-semibold">Siparişlerim</h2>
        {orders.length === 0 ? (
          <div className="rounded-xl bg-card p-6 text-center text-muted">
            Henüz üye olarak verdiğin bir sipariş yok.{" "}
            <Link href="/" className="text-brand underline">
              Etkinliklere göz at
            </Link>
          </div>
        ) : (
          <ul className="flex flex-col gap-3">
            {orders.map((o) => {
              const cat = categoryInfo(o.event.category);
              const tickets = o.items.reduce((n, i) => n + i.quantity, 0);
              return (
                <li key={o.code}>
                  <Link
                    href={`/siparis/${o.code}`}
                    className="flex items-center gap-4 rounded-xl border border-black/10 p-4 transition hover:border-brand dark:border-white/10"
                  >
                    <span className="text-2xl" aria-hidden>
                      {cat.emoji}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{o.event.title}</p>
                      <p className="text-sm text-muted">
                        {formatDateShort(o.event.starts_at)} · {o.event.venue.city} · {tickets} bilet
                      </p>
                      <p className="mt-0.5 font-mono text-xs text-muted">{o.code}</p>
                    </div>
                    <div className="text-right">
                      <p className="font-semibold tabular-nums">{formatTL(o.total_amount)}</p>
                      <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-xs ${STATUS_STYLE[o.status]}`}>
                        {statusLabel[o.status]}
                      </span>
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
        {!user.email_verified && (
          <p className="mt-4 text-xs text-muted">
            Üye olmadan önce bu e-postayla aldığın biletler, e-posta doğrulaması devreye girdiğinde burada görünecek.
          </p>
        )}
      </section>
    </div>
  );
}
