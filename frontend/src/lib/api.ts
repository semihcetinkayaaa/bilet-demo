// Backend (FastAPI) ile konuşan yardımcılar.
// Sadece sunucu tarafında (Server Component / Server Action) kullanılır;
// API_URL tarayıcıya hiç gönderilmez.

export type Category = "concert" | "match" | "cinema" | "theater";
export type OrderStatus = "pending" | "paid" | "failed" | "cancelled";

export type Venue = { id: number; name: string; city: string; address: string | null };

export type EventSummary = {
  id: number;
  category: Category;
  title: string;
  starts_at: string;
  image_url: string | null;
  venue: Venue;
  min_price: string | null;
  remaining: number;
};

export type TicketType = { id: number; name: string; price: string; remaining: number };

export type EventDetail = EventSummary & {
  description: string | null;
  ticket_types: TicketType[];
};

export type Order = {
  code: string;
  status: OrderStatus;
  buyer_name: string;
  buyer_email_masked: string;
  total_amount: string;
  created_at: string;
  paid_at: string | null;
  event: EventSummary;
  items: { ticket_type_name: string; quantity: number; unit_price: string; line_total: string }[];
};

export type User = { id: number; name: string; email: string; email_verified: boolean; created_at: string };
export type AuthResult = { token: string; expires_at: string; user: User };

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const API_URL = (process.env.API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init);
  return res.json() as Promise<T>;
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(503, "Bilet sistemine şu an ulaşılamıyor. Lütfen biraz sonra tekrar deneyin.");
  }
  if (!res.ok) {
    let message = "Beklenmeyen bir hata oluştu.";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = "Lütfen bilgileri kontrol edin.";
    } catch {}
    throw new ApiError(res.status, message);
  }
  return res;
}

export async function getEvents(
  filters: { category?: string; city?: string; q?: string; limit?: number; offset?: number } = {},
): Promise<{ events: EventSummary[]; total: number }> {
  const qs = new URLSearchParams();
  if (filters.category) qs.set("category", filters.category);
  if (filters.city) qs.set("city", filters.city);
  if (filters.q) qs.set("q", filters.q.slice(0, 100));
  if (filters.limit) qs.set("limit", String(filters.limit));
  if (filters.offset) qs.set("offset", String(filters.offset));
  const res = await send(`/events?${qs}`);
  const events = (await res.json()) as EventSummary[];
  const total = Number(res.headers.get("X-Total-Count") ?? events.length);
  return { events, total };
}

export const getCities = () => request<string[]>("/events/cities");
export const getEvent = (id: string | number) => request<EventDetail>(`/events/${encodeURIComponent(id)}`);
export const getOrder = (code: string) => request<Order>(`/orders/${encodeURIComponent(code)}`);

const bearer = (token?: string): HeadersInit => (token ? { Authorization: `Bearer ${token}` } : {});

export const createOrder = (
  body: { buyer_name: string; buyer_email: string; items: { ticket_type_id: number; quantity: number }[] },
  token?: string,
) => request<Order>("/orders", { method: "POST", body: JSON.stringify(body), headers: bearer(token) });

// Üyelik
export const register = (body: { name: string; email: string; password: string }) =>
  request<AuthResult>("/auth/register", { method: "POST", body: JSON.stringify(body) });
export const login = (body: { email: string; password: string }) =>
  request<AuthResult>("/auth/login", { method: "POST", body: JSON.stringify(body) });
export const logout = (token: string) =>
  send("/auth/logout", { method: "POST", headers: bearer(token) }).then(() => undefined);
export const getMe = (token: string) => request<User>("/auth/me", { headers: bearer(token) });
export const getMyOrders = (token: string) => request<Order[]>("/me/orders", { headers: bearer(token) });

export const payOrder = (
  code: string,
  body: { card_holder: string; card_number: string; expiry: string; cvc: string },
) => request<Order>(`/orders/${encodeURIComponent(code)}/pay`, { method: "POST", body: JSON.stringify(body) });
