"use client";

import Link from "next/link";

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  return (
    <main className="mx-auto max-w-screen-2xl px-6 py-12">
      <div className="rounded-md border border-destructive/50 bg-destructive/5 p-6">
        <h1 className="text-lg font-semibold text-destructive">
          Failed to load ticker
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">{error.message}</p>
        <div className="mt-4 flex gap-3">
          <button
            type="button"
            onClick={reset}
            className="rounded-md border border-input bg-background px-3 py-1.5 text-sm hover:bg-accent"
          >
            Retry
          </button>
          <Link
            href="/"
            className="rounded-md border border-input bg-background px-3 py-1.5 text-sm hover:bg-accent"
          >
            Back to tickers
          </Link>
        </div>
      </div>
    </main>
  );
}
