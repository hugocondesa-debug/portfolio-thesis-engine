/**
 * Pipeline run log shape — Sprint 0.2 backend will expose
 * ``/api/tickers/{ticker}/runs`` returning a list of these.
 *
 * Sprint 1C ships only the type definition (Section 16 falls back to
 * canonical/valuation metadata until the endpoint is wired).
 */

export type PipelineStageStatus = "ok" | "skip" | "fail" | "warn";

export type PipelineStageName =
  | "check_ingestion"
  | "load_wacc"
  | "load_extraction"
  | "validate_extraction"
  | "cross_check"
  | "decompose_notes"
  | "extract_canonical"
  | "persist"
  | "guardrails"
  | "valuate"
  | "persist_valuation"
  | "compose_ficha";

export interface PipelineStage {
  stage: PipelineStageName;
  status: PipelineStageStatus;
  duration_ms: number;
  message: string;
  data: Record<string, unknown>;
}

export interface PipelineRunLog {
  ticker: string;
  run_id: string;
  started_at: string;
  finished_at: string;
  success: boolean;
  stages: PipelineStage[];
}
