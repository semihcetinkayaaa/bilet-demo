"use client";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-xl px-4 py-20 text-center">
      <div className="text-5xl">⚠️</div>
      <h1 className="mt-4 text-2xl font-bold">Bir şeyler ters gitti</h1>
      <p className="mt-2 text-muted">Bilet sistemine şu an ulaşılamıyor olabilir. Lütfen biraz sonra tekrar deneyin.</p>
      <button onClick={reset} className="btn mt-6">
        Tekrar dene
      </button>
    </div>
  );
}
