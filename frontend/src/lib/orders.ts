import { notFound } from "next/navigation";
import { ApiError, getOrder } from "./api";

const CODE_RE = /^BLT-[2-9A-Z]{6}$/i;

/** Siparişi getirir; kod geçersizse ya da sipariş yoksa 404 sayfasını gösterir. */
export async function loadOrderOr404(code: string) {
  if (!CODE_RE.test(code)) notFound();
  try {
    return await getOrder(code);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
