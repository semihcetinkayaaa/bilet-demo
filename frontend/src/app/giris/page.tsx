import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthCard, AuthPageContent } from "@/components/auth-page";

export const metadata: Metadata = { title: "Giriş yap", robots: { index: false } };

export default function LoginPage({ searchParams }: PageProps<"/giris">) {
  return (
    <AuthCard title="Giriş yap" subtitle="Siparişlerini görmek ve daha hızlı bilet almak için.">
      <Suspense fallback={<div className="h-72 animate-pulse rounded-xl bg-background" />}>
        <AuthPageContent mode="giris" searchParams={searchParams} />
      </Suspense>
    </AuthCard>
  );
}
