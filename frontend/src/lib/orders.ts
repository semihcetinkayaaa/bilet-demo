import { notFound } from "next/navigation";
import { ApiError, getOrder } from "./api";

const CODE_RE = /^BLT-[2-9A-Z]{6}$/;

/**
 * Kullanıcının yazdığı kodu standart biçime çevirir: "blt 7k3qx9", "7K3QX9", "BLT-7K3QX9" -> "BLT-7K3QX9".
 * Geçersizse null döner.
 */
export function normalizeOrderCode(input: string): string | null {
  const raw = input.toUpperCase().replace(/[^0-9A-Z]/g, "");
  const body = raw.startsWith("BLT") && raw.length === 9 ? raw.slice(3) : raw;
  const code = `BLT-${body}`;
  return CODE_RE.test(code) ? code : null;
}

/** Siparişi getirir; kod geçersizse ya da sipariş yoksa 404 sayfasını gösterir. */
export async function loadOrderOr404(code: string) {
  const normalized = normalizeOrderCode(code);
  if (!normalized) notFound();
  try {
    return await getOrder(normalized);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
