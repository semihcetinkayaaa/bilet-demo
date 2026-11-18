import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-xl px-4 py-20 text-center">
      <div className="text-5xl">🎟️</div>
      <h1 className="mt-4 text-2xl font-bold">Aradığın sayfa bulunamadı</h1>
      <p className="mt-2 text-muted">Etkinlik kaldırılmış, satışı bitmiş ya da adres hatalı olabilir.</p>
      <Link href="/" className="btn mt-6">
        Etkinliklere dön
      </Link>
    </div>
  );
}
