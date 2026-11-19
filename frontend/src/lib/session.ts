// Oturum çerezi ve mevcut kullanıcı. Sadece sunucu tarafında kullanılır.
//
// Çerezde rastgele bir oturum anahtarı durur (httpOnly: tarayıcıdaki JavaScript okuyamaz).
// Anahtarın geçerliliğini backend kontrol eder; burada kullanıcı bilgisi saklanmaz.
// Not: cookies() okuyan bileşenler <Suspense> içinde olmalı (Cache Components kuralı).

import { cookies } from "next/headers";
import { ApiError, getMe, type User } from "./api";

export const SESSION_COOKIE = "bilet_oturum";

export async function getSessionToken(): Promise<string | undefined> {
  return (await cookies()).get(SESSION_COOKIE)?.value;
}

/** Giriş yapılmışsa kullanıcıyı, yapılmamışsa (ya da oturum geçersizse) null döndürür. */
export async function getCurrentUser(): Promise<User | null> {
  const token = await getSessionToken();
  if (!token) return null;
  try {
    return await getMe(token);
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}

export async function setSessionCookie(token: string, expiresAt: string) {
  (await cookies()).set(SESSION_COOKIE, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    expires: new Date(expiresAt),
  });
}

export async function clearSessionCookie() {
  (await cookies()).delete(SESSION_COOKIE);
}

/** Giriş sonrası dönülecek adres: sadece site içi yollar (açık yönlendirme açığına karşı). */
export function safeNext(next: string | null | undefined, fallback = "/hesabim"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  return next.slice(0, 300);
}
