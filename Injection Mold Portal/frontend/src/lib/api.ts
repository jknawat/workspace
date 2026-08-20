import type {
  AdminStats,
  Customer,
  Material,
  Order,
  OrderStatus,
  QuoteInput,
  QuoteResult,
  User,
} from "./types";

// In dev, Vite proxies /api to the local backend (see vite.config.ts), so a
// relative path works. In production the frontend and backend are deployed
// separately — VITE_API_URL must point at the backend's public origin.
const API_BASE = import.meta.env.VITE_API_URL ?? "";

const TOKEN_KEY = "imp_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const isFormData = options.body instanceof FormData;
  const res = await fetch(`${API_BASE}/api${path}`, {
    ...options,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(body.error ?? `Request failed with ${res.status}`, res.status);
  }
  return body as T;
}

export interface CadGeometry {
  triangleCount: number;
  volumeCm3: number;
  surfaceAreaCm2: number;
  bboxXMm: number;
  bboxYMm: number;
  bboxZMm: number;
  estimatedWallThicknessMm: number | null;
}

export const api = {
  materials: () => request<{ materials: Material[] }>("/materials"),

  quote: (input: QuoteInput) =>
    request<{ input: QuoteInput; result: QuoteResult }>("/quote", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  parseCad: (file: File, materialId: string) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ filename: string; geometry: CadGeometry; estimatedWeightG: number }>(
      `/cad/parse?materialId=${materialId}`,
      { method: "POST", body: form },
    );
  },

  login: (email: string, password: string) =>
    request<{ token: string; user: User }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  register: (email: string, password: string, companyName: string) =>
    request<{ token: string; user: User }>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, companyName }),
    }),

  me: () => request<{ user: User }>("/auth/me"),

  orders: () => request<{ orders: Order[] }>("/orders"),

  order: (id: string) => request<{ order: Order }>(`/orders/${id}`),

  createOrder: (input: QuoteInput, cadFile?: File | null) => {
    const form = new FormData();
    form.append("input", JSON.stringify(input));
    if (cadFile) form.append("cadFile", cadFile);
    return request<{ order: Order }>("/orders", { method: "POST", body: form });
  },

  checkout: (orderId: string) =>
    request<{ checkoutUrl: string }>(`/orders/${orderId}/checkout`, { method: "POST" }),

  admin: {
    stats: () => request<AdminStats>("/admin/stats"),
    orders: () => request<{ orders: Order[] }>("/admin/orders"),
    order: (id: string) => request<{ order: Order }>(`/admin/orders/${id}`),
    updateOrderStatus: (id: string, status: OrderStatus) =>
      request<{ order: Order }>(`/admin/orders/${id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }),
    customers: () => request<{ customers: Customer[] }>("/admin/customers"),
  },
};

export { ApiError };
