import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { TicketForm } from "@/components/ticket-form";
import { ApiError, getEvent } from "@/lib/api";
import { categoryGradient, categoryInfo, formatDateLong } from "@/lib/format";
import { getCurrentUser } from "@/lib/session";

export default function EventPage({ params }: PageProps<"/etkinlik/[id]">) {
  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      <Link href="/" className="text-sm text-muted hover:text-foreground">
        ← Tüm etkinlikler
      </Link>
      <Suspense fallback={<div className="mt-6 h-96 animate-pulse rounded-2xl bg-card" />}>
        <EventContent id={params.then((p) => p.id)} />
      </Suspense>
    </div>
  );
}

async function EventContent({ id }: { id: Promise<string> }) {
  const eventId = await id;
  if (!/^\d+$/.test(eventId)) notFound();

  let event;
  try {
    event = await getEvent(eventId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }

  let buyer = null;
  try {
    buyer = await getCurrentUser();
  } catch {}

  const cat = categoryInfo(event.category);
  return (
    <div className="mt-6 grid gap-10 lg:grid-cols-[1fr_420px]">
      <article>
        <div className={`flex h-56 items-end rounded-2xl bg-gradient-to-br ${categoryGradient[event.category]} p-6 text-white`}>
          <div>
            <span className="rounded-full bg-black/25 px-2.5 py-1 text-xs font-medium">
              {cat.emoji} {cat.label}
            </span>
            <h1 className="mt-3 text-3xl font-bold leading-tight">{event.title}</h1>
          </div>
        </div>
        <dl className="mt-6 grid gap-4 sm:grid-cols-2">
          <div className="rounded-xl bg-card p-4">
            <dt className="text-xs uppercase tracking-wide text-muted">Tarih</dt>
            <dd className="mt-1 font-medium">{formatDateLong(event.starts_at)}</dd>
          </div>
          <div className="rounded-xl bg-card p-4">
            <dt className="text-xs uppercase tracking-wide text-muted">Mekan</dt>
            <dd className="mt-1 font-medium">{event.venue.name}</dd>
            <dd className="text-sm text-muted">
              {event.venue.address ? `${event.venue.address}, ` : ""}
              {event.venue.city}
            </dd>
          </div>
        </dl>
        {event.description && <p className="mt-6 leading-relaxed">{event.description}</p>}
      </article>

      <aside>
        <h2 className="mb-4 text-lg font-semibold">Bilet seç</h2>
        {event.remaining === 0 ? (
          <p className="rounded-xl bg-card p-6 text-center text-muted">Bu etkinliğin tüm biletleri tükendi.</p>
        ) : (
          <TicketForm ticketTypes={event.ticket_types} buyer={buyer} />
        )}
      </aside>
    </div>
  );
}
