import Link from "next/link";
import { Suspense } from "react";
import { EventCard, EventGridSkeleton } from "@/components/event-card";
import { ApiError, getCities, getEvents } from "@/lib/api";
import { BRAND, CATEGORIES } from "@/lib/format";

type Filters = { kategori?: string; sehir?: string };

function pick(v: string | string[] | undefined) {
  return Array.isArray(v) ? v[0] : v;
}

export default function HomePage({ searchParams }: PageProps<"/">) {
  // searchParams sadece Suspense içinde okunur; sayfanın geri kalanı önceden hazırlanır.
  const filters = searchParams.then((sp) => ({ kategori: pick(sp.kategori), sehir: pick(sp.sehir) }));

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <section className="mb-10">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Bu akşam nereye?</h1>
        <p className="mt-2 text-muted">
          Konser, maç, sinema ve tiyatro biletleri {BRAND}&apos;da. Birkaç tıkla biletin e-postanda.
        </p>
      </section>

      <Suspense fallback={<div className="mb-8 h-20" />}>
        <FilterBar filters={filters} />
      </Suspense>

      <Suspense fallback={<EventGridSkeleton />}>
        <EventList filters={filters} />
      </Suspense>
    </div>
  );
}

function chip(active: boolean) {
  return `rounded-full border px-4 py-1.5 text-sm transition ${
    active
      ? "border-brand bg-brand text-brand-foreground"
      : "border-black/15 hover:border-brand dark:border-white/15"
  }`;
}

function href(f: Filters) {
  const qs = new URLSearchParams();
  if (f.kategori) qs.set("kategori", f.kategori);
  if (f.sehir) qs.set("sehir", f.sehir);
  const q = qs.toString();
  return q ? `/?${q}` : "/";
}

async function FilterBar({ filters }: { filters: Promise<Filters> }) {
  const f = await filters;
  let cities: string[] = [];
  try {
    cities = await getCities();
  } catch {}

  return (
    <div className="mb-8 flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Link href={href({ sehir: f.sehir })} className={chip(!f.kategori)}>
          Tümü
        </Link>
        {CATEGORIES.map((c) => (
          <Link key={c.value} href={href({ ...f, kategori: c.value })} className={chip(f.kategori === c.value)}>
            {c.emoji} {c.label}
          </Link>
        ))}
      </div>
      {cities.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">Şehir:</span>
          <Link href={href({ kategori: f.kategori })} className={chip(!f.sehir)}>
            Hepsi
          </Link>
          {cities.map((city) => (
            <Link key={city} href={href({ ...f, sehir: city })} className={chip(f.sehir === city)}>
              {city}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

async function EventList({ filters }: { filters: Promise<Filters> }) {
  const f = await filters;
  const category = CATEGORIES.some((c) => c.value === f.kategori) ? f.kategori : undefined;

  let events;
  try {
    events = await getEvents({ category, city: f.sehir });
  } catch (e) {
    return (
      <p className="rounded-xl bg-card p-6 text-center text-muted">
        {e instanceof ApiError ? e.message : "Etkinlikler yüklenemedi."}
      </p>
    );
  }

  if (events.length === 0) {
    return (
      <p className="rounded-xl bg-card p-6 text-center text-muted">
        Bu filtrelere uygun yaklaşan etkinlik yok.{" "}
        <Link href="/" className="text-brand underline">
          Tüm etkinlikleri gör
        </Link>
      </p>
    );
  }

  return (
    <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
      {events.map((e) => (
        <EventCard key={e.id} event={e} />
      ))}
    </div>
  );
}
