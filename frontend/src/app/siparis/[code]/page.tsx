import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { OrderSummary } from "@/components/order-summary";
import { statusLabel } from "@/lib/format";
import { loadOrderOr404 } from "@/lib/orders";

export const metadata: Metadata = { title: "Sipariş", robots: { index: false } };

export default function OrderPage({ params, searchParams }: PageProps<"/siparis/[code]">) {
  const data = Promise.all([params, searchParams]).then(([p, sp]) => ({
    code: p.code,
    error: typeof sp.hata === "string" ? sp.hata.slice(0, 200) : undefined,
  }));
  return (
    <div className="mx-auto max-w-xl px-4 py-10">
      <Suspense fallback={<div className="h-96 animate-pulse rounded-2xl bg-card" />}>
        <OrderContent data={data} />
      </Suspense>
    </div>
  );
}

async function OrderContent({ data }: { data: Promise<{ code: string; error?: string }> }) {
  const { code, error } = await data;
  const order = await loadOrderOr404(code);

  const header =
    order.status === "paid" ? (
      <>
        <div className="text-5xl">🎉</div>
        <h1 className="mt-3 text-2xl font-bold">Biletlerin hazır!</h1>
        <p className="mt-2 text-muted">
          Onay e-postası <span className="font-medium text-foreground">{order.buyer_email_masked}</span> adresine
          gönderilecek. Girişte sipariş kodunu göstermen yeterli.
        </p>
      </>
    ) : order.status === "pending" ? (
      <>
        <h1 className="text-2xl font-bold">Ödeme bekleniyor</h1>
        <p className="mt-2 text-muted">Bu siparişin ödemesi henüz tamamlanmadı.</p>
        <Link href={`/odeme/${order.code}`} className="btn mt-4">
          Ödemeye devam et
        </Link>
      </>
    ) : (
      <>
        <div className="text-5xl">😕</div>
        <h1 className="mt-3 text-2xl font-bold">{statusLabel[order.status]}</h1>
        <p className="mt-2 text-muted">{error ?? "Bu sipariş tamamlanamadı."} Ücret alınmadı.</p>
        <Link href={`/etkinlik/${order.event.id}`} className="btn mt-4">
          Tekrar dene
        </Link>
      </>
    );

  return (
    <div className="flex flex-col gap-8">
      <div className="text-center">{header}</div>
      <OrderSummary order={order} />
      <p className="text-center text-sm">
        <Link href="/" className="text-brand underline">
          Diğer etkinliklere göz at
        </Link>
      </p>
    </div>
  );
}
