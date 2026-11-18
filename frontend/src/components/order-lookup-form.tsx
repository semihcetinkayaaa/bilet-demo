"use client";

import { useActionState } from "react";
import { findOrderAction, type FormState } from "@/app/actions";

export function OrderLookupForm() {
  const [state, formAction, pending] = useActionState<FormState, FormData>(findOrderAction, {});

  return (
    <form action={formAction} className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-sm">
        Sipariş kodu
        <input
          name="code"
          required
          placeholder="BLT-7K3QX9"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          maxLength={20}
          className="input font-mono uppercase"
        />
      </label>
      {state.error && (
        <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-200">
          {state.error}
        </p>
      )}
      <button type="submit" className="btn" disabled={pending}>
        {pending ? "Aranıyor…" : "Siparişi bul"}
      </button>
    </form>
  );
}
