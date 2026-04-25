"use client";

import { useState, type ChangeEvent, type FormEvent } from "react";
import type { ValidationError, YamlUploadResult } from "@/lib/types/api";

interface Props {
  ticker: string;
  name: string;
}

export function YamlUploadForm({ ticker, name }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<YamlUploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    setFile(e.target.files?.[0] ?? null);
    setResult(null);
    setError(null);
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!file) return;

    setPending(true);
    setError(null);
    setResult(null);

    try {
      const text = await file.text();
      const res = await fetch(
        `/api/yamls/${encodeURIComponent(ticker)}/${encodeURIComponent(name)}`,
        {
          method: "POST",
          headers: { "Content-Type": "text/plain" },
          body: text,
        },
      );

      const body: unknown = await res.json();

      if (!res.ok) {
        const detail = extractDetail(body);
        if (detail) {
          setResult(detail);
        } else {
          setError(`HTTP ${res.status}`);
        }
      } else {
        if (isUploadResult(body)) {
          setResult(body);
        } else {
          setError("Unexpected response shape");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="file"
          accept=".yaml,.yml"
          onChange={onFileChange}
          className="block text-sm file:mr-3 file:rounded-md file:border file:border-input file:bg-background file:px-3 file:py-1.5 file:text-sm hover:file:bg-accent"
        />
        <button
          type="submit"
          disabled={!file || pending}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {pending ? "Uploading…" : "Upload"}
        </button>
      </div>

      {error ? (
        <div className="rounded-md border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {result?.success ? (
        <div className="rounded-md border border-positive/50 bg-positive/5 p-3 text-sm">
          <p className="font-medium text-positive">Upload accepted.</p>
          {result.backup_path ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Previous version backed up to{" "}
              <code>{result.backup_path}</code>
            </p>
          ) : null}
        </div>
      ) : null}

      {result && !result.success && result.validation_errors ? (
        <ValidationErrorList errors={result.validation_errors} />
      ) : null}
    </form>
  );
}

function ValidationErrorList({ errors }: { errors: ValidationError[] }) {
  return (
    <div className="rounded-md border border-destructive/50 bg-destructive/5 p-3 text-sm">
      <p className="mb-2 font-medium text-destructive">
        Validation failed ({errors.length} error{errors.length === 1 ? "" : "s"})
      </p>
      <ul className="space-y-1.5 text-xs">
        {errors.map((err, i) => (
          <li key={i} className="font-mono">
            {err.loc && err.loc.length > 0 ? (
              <span className="text-muted-foreground">
                [{err.loc.join(".")}]{" "}
              </span>
            ) : null}
            <span>{err.message}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function isUploadResult(body: unknown): body is YamlUploadResult {
  return (
    typeof body === "object"
    && body !== null
    && "success" in body
    && typeof (body as { success: unknown }).success === "boolean"
  );
}

function extractDetail(body: unknown): YamlUploadResult | null {
  if (typeof body !== "object" || body === null) return null;
  const detail = (body as { detail?: unknown }).detail;
  if (isUploadResult(detail)) return detail;
  return null;
}
