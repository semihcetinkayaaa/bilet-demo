"use server";

// Formlardan gelen istekleri backend'e ileten Server Action'lar.
// Tarayıcı backend'le doğrudan konuşmaz; doğrulamanın asıl yeri yine backend'dir.

import { redirect } from "next/navigation";
import { ApiError, createOrder, getOrder, login, logout, payOrder, register } from "@/lib/api";
import { normalizeOrderCode } from "@/lib/orders";
import { clearSessionCookie, getSessionToken, safeNext, setSessionCookie } from "@/lib/session";

export type FormState = { error?: string };

const str = (fd: FormData, key: string) => String(fd.get(key) ?? "").trim();

export async function createOrderAction(_prev: FormState, fd: FormData): Promise<FormState> {
  const items: { ticket_type_id: number; quantity: number }[] = [];
  for (const [key, value] of fd.entries()) {
    if (!key.startsWith("qty_")) continue;
    const quantity = Number(value);
    const id = Number(key.slice(4));
    if (Number.isInteger(id) && Number.isInteger(quantity) && quantity > 0) {
      items.push({ ticket_type_id: id, quantity });
    }
  }
  if (items.length === 0) return { error: "Lütfen en az bir bilet seçin." };

  const buyer_name = str(fd, "buyer_name");
  const buyer_email = str(fd, "buyer_email");
  if (buyer_name.length < 2) return { error: "Lütfen adınızı ve soyadınızı yazın." };
  if (!buyer_email.includes("@")) return { error: "Lütfen geçerli bir e-posta adresi yazın." };

  let code: string;
  try {
    // Giriş yapılmışsa oturum anahtarı gönderilir; sipariş üyenin hesabına bağlanır.
    code = (await createOrder({ buyer_name, buyer_email, items }, await getSessionToken())).code;
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Sipariş oluşturulamadı." };
  }
  redirect(`/odeme/${code}`);
}

// --------------------------------------------------------------------------- üyelik

export type AuthFormState = { error?: string; email?: string; name?: string };

export async function registerAction(_prev: AuthFormState, fd: FormData): Promise<AuthFormState> {
  const name = str(fd, "name");
  const email = str(fd, "email");
  const password = String(fd.get("password") ?? "");
  const keep = { email, name };
  if (name.length < 2) return { ...keep, error: "Lütfen adınızı ve soyadınızı yazın." };
  if (!email.includes("@")) return { ...keep, error: "Lütfen geçerli bir e-posta adresi yazın." };
  if (password.length < 8) return { ...keep, error: "Şifre en az 8 karakter olmalı." };
  if (password !== String(fd.get("password2") ?? "")) return { ...keep, error: "Şifreler birbirini tutmuyor." };

  try {
    const res = await register({ name, email, password });
    await setSessionCookie(res.token, res.expires_at);
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) return { ...keep, error: "Lütfen bilgileri kontrol edin." };
    return { ...keep, error: e instanceof ApiError ? e.message : "Kayıt yapılamadı." };
  }
  redirect(safeNext(str(fd, "sonra")));
}

export async function loginAction(_prev: AuthFormState, fd: FormData): Promise<AuthFormState> {
  const email = str(fd, "email");
  const password = String(fd.get("password") ?? "");
  if (!email || !password) return { email, error: "E-posta ve şifrenizi yazın." };

  try {
    const res = await login({ email, password });
    await setSessionCookie(res.token, res.expires_at);
  } catch (e) {
    return { email, error: e instanceof ApiError ? e.message : "Giriş yapılamadı." };
  }
  redirect(safeNext(str(fd, "sonra")));
}

export async function logoutAction(): Promise<void> {
  const token = await getSessionToken();
  if (token) {
    try {
      await logout(token); // backend'de oturumu sil
    } catch {}
  }
  await clearSessionCookie();
  redirect("/");
}

export async function findOrderAction(_prev: FormState, fd: FormData): Promise<FormState> {
  const code = normalizeOrderCode(str(fd, "code"));
  if (!code) return { error: "Sipariş kodu BLT-XXXXXX biçiminde olmalı (ör. BLT-7K3QX9)." };
  try {
    await getOrder(code);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      return { error: "Bu koda ait bir sipariş bulunamadı. Kodu e-postandaki gibi yazdığından emin ol." };
    }
    return { error: e instanceof ApiError ? e.message : "Sipariş sorgulanamadı." };
  }
  redirect(`/siparis/${code}`);
}

export async function payOrderAction(code: string, _prev: FormState, fd: FormData): Promise<FormState> {
  try {
    await payOrder(code, {
      card_holder: str(fd, "card_holder"),
      card_number: str(fd, "card_number"),
      expiry: str(fd, "expiry"),
      cvc: str(fd, "cvc"),
    });
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) {
      return { error: "Kart bilgilerini kontrol edin (son kullanma AA/YY, CVC 3-4 hane)." };
    }
    if (e instanceof ApiError && (e.status === 402 || e.status === 409)) {
      // Sipariş artık ödenemez durumda; sonuç sayfası durumu gösterir.
      redirect(`/siparis/${code}?hata=${encodeURIComponent(e.message)}`);
    }
    return { error: e instanceof ApiError ? e.message : "Ödeme yapılamadı." };
  }
  redirect(`/siparis/${code}`);
}
