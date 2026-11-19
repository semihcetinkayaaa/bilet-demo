import Link from "next/link";
import { getCurrentUser } from "@/lib/session";

/** Üst menüdeki kullanıcı alanı. Layout'ta <Suspense> içinde kullanılır (çerez okur). */
export async function UserMenu() {
  let user = null;
  try {
    user = await getCurrentUser();
  } catch {
    // Backend'e ulaşılamazsa menü misafir gibi görünsün; sayfa yine açılsın.
  }

  if (!user) {
    return (
      <Link href="/giris" className="rounded-full bg-brand px-4 py-1.5 text-sm font-medium text-brand-foreground hover:opacity-90">
        Giriş yap
      </Link>
    );
  }
  const first = user.name.split(" ")[0];
  return (
    <Link
      href="/hesabim"
      className="flex items-center gap-2 rounded-full border border-black/15 py-1 pl-1 pr-3 text-sm hover:border-brand dark:border-white/15"
    >
      <span className="flex size-7 items-center justify-center rounded-full bg-brand text-xs font-bold text-brand-foreground">
        {first.charAt(0).toLocaleUpperCase("tr")}
      </span>
      <span className="max-w-28 truncate">{first}</span>
    </Link>
  );
}
