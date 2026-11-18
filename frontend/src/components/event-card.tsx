import Link from "next/link";
import type { EventSummary } from "@/lib/api";
import { categoryGradient, categoryInfo, formatDateShort, formatTL } from "@/lib/format";

export function EventCard({ event }: { event: EventSummary }) {
  const cat = categoryInfo(event.category);
  const soldOut = event.remaining === 0;
  return (
    <Link
      href={`/etkinlik/${event.id}`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-black/10 bg-card transition hover:-translate-y-0.5 hover:shadow-lg dark:border-white/10"
    >
      <div className={`relative h-36 bg-gradient-to-br ${categoryGradient[event.category]} p-4 text-white`}>
        <span className="rounded-full bg-black/25 px-2.5 py-1 text-xs font-medium backdrop-blur">
          {cat.emoji} {cat.label}
        </span>
        {soldOut && (
          <span className="absolute right-4 top-4 rounded-full bg-black/60 px-2.5 py-1 text-xs font-semibold">
            Tükendi
          </span>
        )}
        <span className="absolute bottom-3 right-4 text-5xl opacity-30 transition group-hover:scale-110">
          {cat.emoji}
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-1 p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-brand">{formatDateShort(event.starts_at)}</p>
        <h3 className="font-semibold leading-snug">{event.title}</h3>
        <p className="text-sm text-muted">
          {event.venue.name}, {event.venue.city}
        </p>
        <p className="mt-auto pt-3 text-sm">
          {event.min_price ? (
            <>
              <span className="text-muted">başlayan fiyatlarla </span>
              <span className="font-semibold">{formatTL(event.min_price)}</span>
            </>
          ) : (
            <span className="text-muted">Satışta bilet yok</span>
          )}
        </p>
      </div>
    </Link>
  );
}

export function EventGridSkeleton() {
  return (
    <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="h-72 animate-pulse rounded-2xl bg-card" />
      ))}
    </div>
  );
}
