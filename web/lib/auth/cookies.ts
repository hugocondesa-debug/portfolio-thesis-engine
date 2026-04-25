"use server";

/**
 * Server-side auth helpers — cookie-based proxy for HTTP Basic Auth.
 *
 * The frontend never stores credentials in localStorage / sessionStorage:
 * :func:`loginAction` verifies them against the API once, then writes the
 * base64-encoded Basic-Auth string into an HTTPOnly cookie that
 * :mod:`lib/api/server.ts` reads on every server-side fetch.
 */

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const COOKIE_NAME = "pte_auth";
const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7; // 7 days
const API_URL = process.env.PTE_API_URL ?? "http://pte-api:8000";

export interface LoginResult {
  success: boolean;
  error?: string;
}

export async function loginAction(
  username: string,
  password: string,
): Promise<LoginResult> {
  if (!username || !password) {
    return { success: false, error: "Username and password required" };
  }

  const credentials = Buffer.from(`${username}:${password}`).toString("base64");

  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/tickers`, {
      headers: { Authorization: `Basic ${credentials}` },
      cache: "no-store",
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Network error";
    return { success: false, error: message };
  }

  if (response.status === 401) {
    return { success: false, error: "Invalid credentials" };
  }
  if (!response.ok) {
    return { success: false, error: `API error: ${response.status}` };
  }

  const cookieStore = await cookies();
  cookieStore.set({
    name: COOKIE_NAME,
    value: credentials,
    httpOnly: true,
    secure: false, // Tailscale provides transport encryption.
    sameSite: "lax",
    maxAge: COOKIE_MAX_AGE_SECONDS,
    path: "/",
  });

  return { success: true };
}

export async function logoutAction(): Promise<void> {
  const cookieStore = await cookies();
  cookieStore.delete(COOKIE_NAME);
  redirect("/login");
}

export async function isAuthenticated(): Promise<boolean> {
  const cookieStore = await cookies();
  return cookieStore.has(COOKIE_NAME);
}
