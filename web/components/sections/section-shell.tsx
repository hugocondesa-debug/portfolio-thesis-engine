/**
 * Sprint QA — re-exports SectionShell + helpers from
 * ``primitives/section-shell``. This file remains as a back-compat
 * shim so existing imports under ``components/sections/section-shell``
 * keep working.
 */

export {
  SectionShell,
  SectionHeader,
  EmptySectionNote,
} from "@/components/primitives/section-shell";
