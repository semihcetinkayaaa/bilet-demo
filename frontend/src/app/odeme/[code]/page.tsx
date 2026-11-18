import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { OrderSummary } from "@/components/order-summary";
import { PaymentForm } from "@/components/payment-form";
import { loadOrderOr404 } from "@/lib/orders";

export const metadata: Metadata = { title: "Ödeme", robots: { index: false } };

export default function PaymentPage({ params }: PageProps<"/odeme/[code]">) {
  return (
    <div className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="mb-6 text-2xl font-bold">Ödeme</h1>
      <Suspense fallback={<div className="h-96 animate-pulse rounded-2xl bg-card" />}>
        <PaymentContent code={params.then((p) => p.code)} />
      </Suspense>
    </div>
  );
}

async function PaymentContent({ code }: { code: Promise<string> }) {
  const order = await loadOrderOr404(await code);
  // Ödenmiş ya da kapanmış siparişler için ödeme formu gösterilmez.
  if (order.status !== "pending") redirect(`/siparis/${order.code}`);

  return (
    <div className="grid gap-8 md:grid-cols-[1fr_380px]">
      <section>
        <h2 className="mb-4 text-lg font-semibold">Kart bilgileri</h2>
        <PaymentForm code={order.code} total={order.total_amount} />
      </section>
      <aside>
        <h2 className="mb-4 text-lg font-semibold">Sipariş özeti</h2>
        <OrderSummary order={order} />
      </aside>
    </div>
  );
}
