"use client";

import { useActionState } from "react";
import { payOrderAction, type FormState } from "@/app/actions";
import { formatTL } from "@/lib/format";

// Kart bilgileri sadece backend'e iletilir; hiçbir yerde saklanmaz.
export function PaymentForm({ code, total }: { code: string; total: string }) {
  const [state, formAction, pending] = useActionState<FormState, FormData>(
    payOrderAction.bind(null, code),
    {},
  );

  return (
    <form action={formAction} className="flex flex-col gap-4">
      <div className="rounded-lg border border-dashed border-brand/50 bg-brand/5 p-3 text-xs leading-relaxed">
        <p className="font-semibold">Demo ödeme: gerçek kart bilgisi girmeyin.</p>
        <p>
          Başarılı ödeme için: <code className="font-mono">4242 4242 4242 4242</code>
        </p>
        <p>
          Reddedilen ödeme için: <code className="font-mono">4000 0000 0000 0002</code>
        </p>
        <p>Son kullanma tarihi ve CVC için herhangi bir değer girebilirsiniz (ör. 12/30, 123).</p>
      </div>

      <fieldset className="grid grid-cols-2 gap-3" disabled={pending}>
        <label className="col-span-2 flex flex-col gap-1 text-sm">
          Kart üzerindeki isim
          <input name="card_holder" required minLength={2} autoComplete="off" className="input" />
        </label>
        <label className="col-span-2 flex flex-col gap-1 text-sm">
          Kart numarası
          <input
            name="card_number"
            required
            inputMode="numeric"
            pattern="[0-9 ]{12,23}"
            placeholder="4242 4242 4242 4242"
            defaultValue="4242 4242 4242 4242"
            autoComplete="off"
            className="input font-mono"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Son kullanma (AA/YY)
          <input
            name="expiry"
            required
            pattern="(0[1-9]|1[0-2])/[0-9]{2}"
            placeholder="12/30"
            defaultValue="12/30"
            autoComplete="off"
            className="input font-mono"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          CVC
          <input
            name="cvc"
            required
            inputMode="numeric"
            pattern="[0-9]{3,4}"
            placeholder="123"
            defaultValue="123"
            autoComplete="off"
            className="input font-mono"
          />
        </label>
      </fieldset>

      {state.error && (
        <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-200">
          {state.error}
        </p>
      )}

      <button type="submit" className="btn w-full" disabled={pending}>
        {pending ? "Ödeme yapılıyor…" : `${formatTL(total)} öde`}
      </button>
    </form>
  );
}
