import type { Category, OrderStatus } from "./api";

export const BRAND = "semihcetinkaya.tech";

export const CATEGORIES: { value: Category; label: string; emoji: string }[] = [
  { value: "concert", label: "Konser", emoji: "🎤" },
  { value: "match", label: "Maç", emoji: "⚽" },
  { value: "cinema", label: "Sinema", emoji: "🎬" },
  { value: "theater", label: "Tiyatro", emoji: "🎭" },
];

export const categoryInfo = (c: Category) => CATEGORIES.find((x) => x.value === c)!;

// Kart görseli yoksa kategoriye göre renk geçişi kullanılır.
export const categoryGradient: Record<Category, string> = {
  concert: "from-fuchsia-600 to-indigo-700",
  match: "from-emerald-600 to-teal-800",
  cinema: "from-amber-500 to-red-700",
  theater: "from-rose-600 to-purple-800",
};

export const statusLabel: Record<OrderStatus, string> = {
  pending: "Ödeme bekleniyor",
  paid: "Ödendi",
  failed: "Ödeme başarısız",
  cancelled: "İptal edildi",
};

const TZ = "Europe/Istanbul";
const tl = new Intl.NumberFormat("tr-TR", { style: "currency", currency: "TRY" });
const dateLong = new Intl.DateTimeFormat("tr-TR", {
  timeZone: TZ,
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const dateShort = new Intl.DateTimeFormat("tr-TR", {
  timeZone: TZ,
  day: "numeric",
  month: "short",
  weekday: "short",
  hour: "2-digit",
  minute: "2-digit",
});

export const formatTL = (v: string | number) => tl.format(Number(v));
export const formatDateLong = (iso: string) => dateLong.format(new Date(iso));
export const formatDateShort = (iso: string) => dateShort.format(new Date(iso));
