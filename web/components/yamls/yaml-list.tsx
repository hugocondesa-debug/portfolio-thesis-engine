import type { YamlListItem } from "@/lib/types/api";
import { formatDateTime, formatNumber } from "@/lib/utils/format";
import { YamlDownloadButton } from "./yaml-download-button";
import { YamlUploadForm } from "./yaml-upload-form";

interface Props {
  ticker: string;
  yamls: YamlListItem[];
}

export function YamlList({ ticker, yamls }: Props) {
  if (yamls.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border bg-card p-6 text-sm text-muted-foreground">
        No editable yamls present for this ticker yet.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      {yamls.map((y) => (
        <YamlCard key={y.name} ticker={ticker} yaml={y} />
      ))}
    </div>
  );
}

function YamlCard({ ticker, yaml }: { ticker: string; yaml: YamlListItem }) {
  return (
    <div className="rounded-md border border-border bg-card p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h3 className="font-mono text-base font-semibold">{yaml.filename}</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Last modified {formatDateTime(yaml.last_modified)} ·{" "}
            {formatNumber(yaml.size_bytes, { compact: true })} B ·{" "}
            {yaml.versions_count} version
            {yaml.versions_count === 1 ? "" : "s"}
          </p>
        </div>

        <YamlDownloadButton
          ticker={ticker}
          name={yaml.name}
          filename={yaml.filename}
        />
      </div>

      <div className="mt-4 border-t border-border pt-4">
        <YamlUploadForm ticker={ticker} name={yaml.name} />
      </div>
    </div>
  );
}
