import { redirect } from "next/navigation";
import { AuthForm } from "@/components/auth-form";
import { getCurrentUser, safeNext } from "@/lib/session";

/** Giriş/kayıt sayfasının içeriği. Suspense içinde çağrılır (çerez ve adres parametresi okur). */
export async function AuthPageContent({
  mode,
  searchParams,
}: {
  mode: "giris" | "kayit";
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const raw = typeof sp.sonra === "string" ? sp.sonra : undefined;
  const next = raw ? safeNext(raw) : undefined;

  // Zaten giriş yapılmışsa formu gösterme
  if (await getCurrentUser()) redirect(next ?? "/hesabim");

  return <AuthForm mode={mode} next={next} />;
}

export function AuthCard({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-md px-4 py-16">
      <div className="text-center">
        <h1 className="text-2xl font-bold">{title}</h1>
        <p className="mt-2 text-muted">{subtitle}</p>
      </div>
      <div className="mt-8 rounded-2xl border border-black/10 bg-card p-6 dark:border-white/10">{children}</div>
    </div>
  );
}
