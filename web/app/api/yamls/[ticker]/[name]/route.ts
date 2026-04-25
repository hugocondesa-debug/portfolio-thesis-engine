import type { NextRequest } from "next/server";
import { serverFetchRaw } from "@/lib/api/server";

interface Params {
  params: Promise<{ ticker: string; name: string }>;
}

export async function GET(_: NextRequest, { params }: Params) {
  const { ticker, name } = await params;
  const upstream = await serverFetchRaw(
    `/api/tickers/${encodeURIComponent(decodeURIComponent(ticker))}/yamls/${encodeURIComponent(decodeURIComponent(name))}`,
  );

  return new Response(upstream.body, {
    status: upstream.status,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}

export async function POST(request: NextRequest, { params }: Params) {
  const { ticker, name } = await params;
  const body = await request.text();
  const upstream = await serverFetchRaw(
    `/api/tickers/${encodeURIComponent(decodeURIComponent(ticker))}/yamls/${encodeURIComponent(decodeURIComponent(name))}`,
    {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body,
    },
  );

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.contentType || "application/json",
    },
  });
}
