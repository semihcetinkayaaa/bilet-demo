import type { Order } from "@/lib/api";
import { categoryInfo, formatDateLong, formatTL } from "@/lib/format";

export function OrderSummary({ order }: { order: Order }) {
  const cat = categoryInfo(order.event.category);
  return (
    <div className="rounded-2xl border border-black/10 bg-card p-5 dark:border-white/10">
      <p className="text-xs uppercase tracking-wide text-muted">
        {cat.emoji} {cat.label}
      </p>
      <h2 className="mt-1 text-lg font-semibold leading-snug">{order.event.title}</h2>
      <p className="mt-1 text-sm text-muted">{formatDateLong(order.event.starts_at)}</p>
      <p className="text-sm text-muted">
        {order.event.venue.name}, {order.event.venue.city}
      </p>

      <ul className="mt-4 divide-y divide-black/10 border-y border-black/10 text-sm dark:divide-white/10 dark:border-white/10">
        {order.items.map((i) => (
          <li key={i.ticket_type_name} className="flex justify-between py-2">
            <span>
              {i.quantity} × {i.ticket_type_name}
            </span>
            <span className="tabular-nums">{formatTL(i.line_total)}</span>
          </li>
        ))}
      </ul>
      <p className="mt-3 flex justify-between font-semibold">
        <span>Toplam</span>
        <span className="tabular-nums">{formatTL(order.total_amount)}</span>
      </p>
      <p className="mt-4 text-xs text-muted">
        Sipariş kodu <span className="font-mono font-semibold text-foreground">{order.code}</span> ·{" "}
        {order.buyer_name} ({order.buyer_email_masked})
      </p>
    </div>
  );
}
