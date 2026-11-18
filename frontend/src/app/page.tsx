import Form from "next/form";
import Link from "next/link";
import { Suspense } from "react";
import { EventCard, EventGridSkeleton } from "@/components/event-card";
import { ApiError, getCities, getEvents } from "@/lib/api";
import { BRAND, CATEGORIES } from "@/lib/format";

type Filters = { kategori?: string; sehir?: string; ara?: string };

function pick(v: string | string[] | undefined) {
  const s = Array.isArray(v) ? v[0] : v;
  return s?.trim() || undefined;
}

export default function HomePage({ searchParams }: PageProps<"/">) {
  // searchParams sadece Suspense içinde okunur; sayfanın geri kalanı önceden hazırlanır.
  const filters = searchParams.then((sp) => ({
    kategori: pick(sp.kategori),
    sehir: pick(sp.sehir),
    ara: pick(sp.ara)?.slice(0, 100),
  }));

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <section className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Bu akşam nereye?</h1>
        <p className="mt-2 text-muted">
          Konser, maç, sinema ve tiyatro biletleri {BRAND}&apos;da. Birkaç tıkla biletin e-postanda.
        </p>
      </section>

      <Suspense fallback={<div className="mb-8 h-36" />}>
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
  if (f.ara) qs.set("ara", f.ara);
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
    <div className="mb-8 flex flex-col gap-4">
      {/* GET formu: aramayı adres çubuğuna ?ara=... olarak yazar, seçili filtreleri korur. */}
      <Form action="/" role="search" className="flex gap-2">
        <label htmlFor="ara" className="sr-only">
          Etkinlik ara
        </label>
        <input
          id="ara"
          // Arama değişince kutu yeni değerle yeniden oluşsun
          key={f.ara ?? ""}
          name="ara"
          type="search"
          defaultValue={f.ara}
          maxLength={100}
          placeholder="Sanatçı, takım, film, oyun ya da mekan ara…"
          className="input flex-1 py-3 text-base"
        />
        {f.kategori && <input type="hidden" name="kategori" value={f.kategori} />}
        {f.sehir && <input type="hidden" name="sehir" value={f.sehir} />}
        <button type="submit" className="btn">
          Ara
        </button>
      </Form>

      <div className="flex flex-wrap gap-2">
        <Link href={href({ ara: f.ara, sehir: f.sehir })} className={chip(!f.kategori)}>
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
          <Link href={href({ ara: f.ara, kategori: f.kategori })} className={chip(!f.sehir)}>
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
    events = await getEvents({ category, city: f.sehir, q: f.ara });
  } catch (e) {
    return (
      <p className="rounded-xl bg-card p-6 text-center text-muted">
        {e instanceof ApiError ? e.message : "Etkinlikler yüklenemedi."}
      </p>
    );
  }

  const searchNote = f.ara && (
    <p className="mb-4 text-sm text-muted">
      <span className="font-medium text-foreground">“{f.ara}”</span> için {events.length} etkinlik bulundu.{" "}
      <Link href={href({ kategori: f.kategori, sehir: f.sehir })} className="text-brand underline">
        Aramayı temizle
      </Link>
    </p>
  );

  if (events.length === 0) {
    return (
      <>
        {searchNote}
        <p className="rounded-xl bg-card p-6 text-center text-muted">
          {f.ara ? "Aramana uygun yaklaşan etkinlik bulunamadı." : "Bu filtrelere uygun yaklaşan etkinlik yok."}{" "}
          <Link href="/" className="text-brand underline">
            Tüm etkinlikleri gör
          </Link>
        </p>
      </>
    );
  }

  return (
    <>
      {searchNote}
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {events.map((e) => (
          <EventCard key={e.id} event={e} />
        ))}
      </div>
    </>
  );
}
