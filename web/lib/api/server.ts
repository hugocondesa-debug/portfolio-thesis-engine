/**
 * Server-side fetch wrapper for use in Server Components and Server Actions.
 *
 * Always reads the cached Basic-Auth string from the HTTPOnly ``pte_auth``
 * cookie set by :mod:`lib/auth/cookies.ts::loginAction`. When the cookie is
 * absent, redirects to ``/login``. When the API answers 401, clears the
 * cookie via redirect (the browser will re-auth).
 */

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const API_URL = process.env.PTE_API_URL ?? "http://pte-api:8000";

export class ServerApiError extends Error {
  readonly statusCode: number;
  readonly path: string;

  constructor(statusCode: number, path: string, message: string) {
    super(message);
    this.name = "ServerApiError";
    this.statusCode = statusCode;
    this.path = path;
  }
}

export async function serverFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const cookieStore = await cookies();
  const authCookie = cookieStore.get("pte_auth");

  if (!authCookie) {
    redirect("/login");
  }

  const headers = new Headers(options.headers);
  headers.set("Authorization", `Basic ${authCookie.value}`);

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });

  if (response.status === 401) {
    redirect("/login");
  }

  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.text();
      detail = body.slice(0, 200);
    } catch {
      // ignore
    }
    throw new ServerApiError(
      response.status,
      path,
      `API ${response.status} on ${path}: ${detail}`,
    );
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("text/plain") || contentType.includes("text/yaml")) {
    return (await response.text()) as T;
  }
  return (await response.json()) as T;
}

/**
 * Variant that does not redirect on 401 — used by the yaml proxy route which
 * needs to surface upstream errors verbatim to the browser.
 */
export async function serverFetchRaw(
  path: string,
  options: RequestInit = {},
): Promise<{ status: number; body: string; contentType: string }> {
  const cookieStore = await cookies();
  const authCookie = cookieStore.get("pte_auth");

  const headers = new Headers(options.headers);
  if (authCookie) {
    headers.set("Authorization", `Basic ${authCookie.value}`);
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });

  return {
    status: response.status,
    body: await response.text(),
    contentType: response.headers.get("content-type") ?? "application/json",
  };
}
