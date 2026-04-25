"use client";

import { useState } from "react";

interface Props {
  ticker: string;
  name: string;
  filename: string;
}

export function YamlDownloadButton({ ticker, name, filename }: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onDownload() {
    setPending(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/yamls/${encodeURIComponent(ticker)}/${encodeURIComponent(name)}`,
      );
      if (!res.ok) throw new Error(`Download failed: ${res.status}`);
      const text = await res.text();

      const blob = new Blob([text], { type: "text/yaml" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={onDownload}
        disabled={pending}
        className="rounded-md border border-input bg-background px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
      >
        {pending ? "Downloading…" : "Download"}
      </button>
      {error ? (
        <span className="text-xs text-destructive">{error}</span>
      ) : null}
    </div>
  );
}
