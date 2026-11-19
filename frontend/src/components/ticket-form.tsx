"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useActionState, useState } from "react";
import { createOrderAction, type FormState } from "@/app/actions";
import type { TicketType } from "@/lib/api";
import { formatTL } from "@/lib/format";

const MAX_PER_ORDER = 10;

export function TicketForm({
  ticketTypes,
  buyer,
}: {
  ticketTypes: TicketType[];
  /** Giriş yapılmışsa ad ve e-posta hazır gelir */
  buyer?: { name: string; email: string } | null;
}) {
  const [state, formAction, pending] = useActionState<FormState, FormData>(createOrderAction, {});
  const [qty, setQty] = useState<Record<number, number>>({});
  const pathname = usePathname();

  const totalCount = Object.values(qty).reduce((a, b) => a + b, 0);
  const totalPrice = ticketTypes.reduce((sum, t) => sum + Number(t.price) * (qty[t.id] ?? 0), 0);

  function change(t: TicketType, delta: number) {
    setQty((q) => {
      const current = q[t.id] ?? 0;
      const othersCount = totalCount - current;
      const next = Math.max(0, Math.min(current + delta, t.remaining, MAX_PER_ORDER - othersCount));
      return { ...q, [t.id]: next };
    });
  }

  return (
    <form action={formAction} className="flex flex-col gap-6">
      <ul className="divide-y divide-black/10 rounded-xl border border-black/10 dark:divide-white/10 dark:border-white/10">
        {ticketTypes.map((t) => {
          const n = qty[t.id] ?? 0;
          const soldOut = t.remaining === 0;
          return (
            <li key={t.id} className="flex items-center gap-4 p-4">
              <div className="flex-1">
                <p className="font-medium">{t.name}</p>
                <p className="text-sm text-muted">
                  {formatTL(t.price)}
                  {soldOut ? " · Tükendi" : t.remaining <= 20 ? ` · Son ${t.remaining} bilet` : ""}
                </p>
              </div>
              <input type="hidden" name={`qty_${t.id}`} value={n} />
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  aria-label={`${t.name} azalt`}
                  onClick={() => change(t, -1)}
                  disabled={n === 0}
                  className="size-9 rounded-full border border-black/15 text-lg disabled:opacity-30 dark:border-white/15"
                >
                  −
                </button>
                <span className="w-6 text-center font-semibold tabular-nums">{n}</span>
                <button
                  type="button"
                  aria-label={`${t.name} artır`}
                  onClick={() => change(t, 1)}
                  disabled={soldOut || n >= t.remaining || totalCount >= MAX_PER_ORDER}
                  className="size-9 rounded-full border border-black/15 text-lg disabled:opacity-30 dark:border-white/15"
                >
                  +
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      <fieldset className="grid gap-3 sm:grid-cols-2" disabled={pending}>
        <legend className="mb-2 text-sm font-semibold">Bilet sahibi</legend>
        <label className="flex flex-col gap-1 text-sm">
          Ad soyad
          <input name="buyer_name" required minLength={2} autoComplete="name" defaultValue={buyer?.name} className="input" />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          E-posta
          <input name="buyer_email" type="email" required autoComplete="email" defaultValue={buyer?.email} className="input" />
        </label>
        <p className="text-xs text-muted sm:col-span-2">
          {buyer ? (
            "Biletlerin bu adrese gönderilecek ve sipariş hesabına kaydedilecek."
          ) : (
            <>
              Biletlerin bu adrese gönderilecek. Üyelik gerekmez.{" "}
              <Link href={`/giris?sonra=${encodeURIComponent(pathname)}`} className="underline">
                Giriş yaparsan
              </Link>{" "}
              siparişlerin hesabında saklanır.
            </>
          )}
        </p>
      </fieldset>

      {state.error && (
        <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-200">
          {state.error}
        </p>
      )}

      <div className="flex items-center justify-between gap-4 rounded-xl bg-card p-4">
        <div>
          <p className="text-sm text-muted">{totalCount} bilet</p>
          <p className="text-xl font-bold">{formatTL(totalPrice)}</p>
        </div>
        <button type="submit" className="btn" disabled={pending || totalCount === 0}>
          {pending ? "Hazırlanıyor…" : "Ödemeye geç"}
        </button>
      </div>
    </form>
  );
}
