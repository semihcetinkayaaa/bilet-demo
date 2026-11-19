"use client";

import Link from "next/link";
import { useActionState } from "react";
import { loginAction, registerAction, type AuthFormState } from "@/app/actions";

export function AuthForm({ mode, next }: { mode: "giris" | "kayit"; next?: string }) {
  const isRegister = mode === "kayit";
  const [state, formAction, pending] = useActionState<AuthFormState, FormData>(
    isRegister ? registerAction : loginAction,
    {},
  );
  const other = isRegister ? "/giris" : "/kayit";
  const otherHref = next ? `${other}?sonra=${encodeURIComponent(next)}` : other;

  return (
    <form action={formAction} className="flex flex-col gap-4">
      {next && <input type="hidden" name="sonra" value={next} />}
      <fieldset className="flex flex-col gap-3" disabled={pending}>
        {isRegister && (
          <label className="flex flex-col gap-1 text-sm">
            Ad soyad
            <input name="name" required minLength={2} autoComplete="name" defaultValue={state.name} className="input" />
          </label>
        )}
        <label className="flex flex-col gap-1 text-sm">
          E-posta
          <input name="email" type="email" required autoComplete="email" defaultValue={state.email} className="input" />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Şifre
          <input
            name="password"
            type="password"
            required
            minLength={isRegister ? 8 : 1}
            maxLength={128}
            autoComplete={isRegister ? "new-password" : "current-password"}
            className="input"
          />
          {isRegister && <span className="text-xs text-muted">En az 8 karakter.</span>}
        </label>
        {isRegister && (
          <label className="flex flex-col gap-1 text-sm">
            Şifre (tekrar)
            <input name="password2" type="password" required minLength={8} maxLength={128} autoComplete="new-password" className="input" />
          </label>
        )}
      </fieldset>

      {state.error && (
        <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-200">
          {state.error}
        </p>
      )}

      <button type="submit" className="btn" disabled={pending}>
        {pending ? "Lütfen bekleyin…" : isRegister ? "Üye ol" : "Giriş yap"}
      </button>

      <p className="text-center text-sm text-muted">
        {isRegister ? "Zaten üye misin? " : "Hesabın yok mu? "}
        <Link href={otherHref} className="text-brand underline">
          {isRegister ? "Giriş yap" : "Üye ol"}
        </Link>
      </p>
      <p className="text-center text-xs text-muted">
        Bilet almak için üye olmak zorunlu değil.{" "}
        <Link href="/" className="underline">
          Üye olmadan devam et
        </Link>
      </p>
    </form>
  );
}
