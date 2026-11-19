import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthCard, AuthPageContent } from "@/components/auth-page";

export const metadata: Metadata = { title: "Üye ol", robots: { index: false } };

export default function RegisterPage({ searchParams }: PageProps<"/kayit">) {
  return (
    <AuthCard title="Üye ol" subtitle="Tüm biletlerin tek yerde, bilgilerin her siparişte hazır.">
      <Suspense fallback={<div className="h-96 animate-pulse rounded-xl bg-background" />}>
        <AuthPageContent mode="kayit" searchParams={searchParams} />
      </Suspense>
    </AuthCard>
  );
}
