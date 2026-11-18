import type { Metadata } from "next";
import { OrderLookupForm } from "@/components/order-lookup-form";

export const metadata: Metadata = { title: "Sipariş sorgula" };

export default function OrderLookupPage() {
  return (
    <div className="mx-auto max-w-md px-4 py-16">
      <div className="text-center">
        <div className="text-5xl">🔎</div>
        <h1 className="mt-3 text-2xl font-bold">Sipariş sorgula</h1>
        <p className="mt-2 text-muted">
          Onay e-postandaki <span className="font-mono">BLT-</span> ile başlayan kodu yazarak biletlerini görüntüle.
        </p>
      </div>
      <div className="mt-8 rounded-2xl border border-black/10 bg-card p-6 dark:border-white/10">
        <OrderLookupForm />
      </div>
    </div>
  );
}
