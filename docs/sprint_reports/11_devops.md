# Sprint 11 — DevOps (provision + backup + systemd)

**Date:** 2026-04-21
**Step (Parte K):** 11 — DevOps
**Status:** ✅ Complete

---

## What was done

Shipped the operational glue that lets the engine live on a VPS under
systemd with daily backups:

- `scripts/provision_vps.sh` — idempotent Ubuntu 24.04 bootstrapper. Detects already-installed packages (`command -v`), debs without a unique binary (`dpkg -s build-essential`), and running services (`systemctl is-active fail2ban`). Skips each step individually. Installs essentials, Python 3.12, uv, Tailscale. Explicitly does NOT touch SSH hardening or ufw (Hugo's VPS has those set manually).
- `scripts/backup.sh` — tar YAMLs, copy DuckDB, SQLite `.backup` for consistency under writes, conditional `rclone sync` gated on a `backup:` remote, 30-day retention sweep on `daily/`, placeholder `weekly/` and `monthly/` directories. Strict mode + log tee to `~/backup.log`.
- `systemd/pte-streamlit.service` — runs the Sprint 10 Streamlit UI under user `portfolio` with `Restart=on-failure` and path-scoped `ProtectSystem=strict` + `ReadWritePaths` hardening.
- `systemd/pte-backup.service` + `pte-backup.timer` — daily at 03:30 local, `Persistent=true` so a VPS that was offline at 03:30 catches up on boot.
- 23 unit tests under `tests/unit/test_devops.py` — bash syntax, strict mode, idempotence primitives, rclone gate, retention age, sqlite `.backup`, systemd unit shape + `[Install]` + `Restart`, Hugo's `User=portfolio` requirement, and a live `systemd-analyze verify` on all three units (skipped automatically if the tool is absent).

## Decisions taken

1. **Idempotent by detection, not by `apt --no-install-recommends`.** Each step checks state before acting:
   - `command -v <bin>` for commands with a unique binary name (git, curl, rclone, tailscale, uv).
   - `dpkg -s <pkg>` for meta-packages (build-essential).
   - `systemctl is-active` for services (fail2ban).
   The alternative — letting apt re-evaluate every install — is slower and produces chatty output even when nothing changes.
2. **Skip / applied accounting surfaces in the summary.** Operators running the script see `+ package` for what was done and `- package (already present)` for what was skipped, plus counts. Makes a re-run's no-op nature obvious.
3. **Not bundled into one `apt install`.** Easier to diagnose which package failed and to skip individually. Trade-off is serial apt calls (~1s each); acceptable because this runs at most weekly.
4. **SSH hardening / ufw NOT managed here.** Hugo flagged this explicitly in the prompt — the VPS is already hardened. Re-running this script would undo nothing, but re-running something that touches sshd_config or ufw rules is dangerous. Cleaner boundary: the script handles "packages + basic services", not "security posture".
5. **`backup.sh` uses `PTE_REPO_ROOT` / `PTE_BACKUP_LOG` env vars** with sensible defaults. systemd service sets them explicitly; local invocation picks up defaults. No hard-coded home directory at the top of the file.
6. **SQLite backup via `.backup` command**, not `cp`. SQLite's own command runs via a read transaction that gets a consistent snapshot even while the engine is writing. `cp` during a write can capture a file in mid-commit state.
7. **Rclone sync is strictly gated.** `command -v rclone` + `rclone listremotes | grep -q '^backup:$'` — both conditions must hold. This means a fresh VPS without rclone configured prints "skipping offsite sync" instead of failing the whole backup.
8. **Weekly / monthly directories are placeholders.** Phase 1 will implement snapshot promotion (copy last Sunday's daily to `weekly/YYYY-Www`, last day-of-month to `monthly/YYYY-MM`). For now the directories exist so operators and rclone see the expected layout.
9. **systemd unit hardening kept conservative.** `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict` with explicit `ReadWritePaths` for `data/` and `backup/`. Does NOT apply `ProtectHome=yes` because the process lives under `/home/portfolio/...` and needs read access to its own repo dir. Enough to stop a compromised Streamlit from clobbering `/etc` or `/usr`, without getting in the way of legitimate writes.
10. **Timer uses `OnCalendar=*-*-* 03:30:00`** with `Persistent=true`. 03:30 local is after most market closes and before European opens; `Persistent=true` covers VPS downtime.
11. **Service-level tests run `systemd-analyze verify`.** The test is marked `skipif` when the tool is missing so CI without systemd (e.g., macOS contributors) still runs the other 22 assertions. On Linux hosts the actual parser sanity-checks every directive.

## Spec auto-corrections

1. **Spec I.1's `provision_vps.sh` was non-idempotent** — it ran `apt upgrade -y` every time and cloned the repo in step 8 (unconditionally). Replaced with detection primitives and removed the repo-clone step (the script runs from inside the already-cloned repo).
2. **Spec I.2's `User=YOUR_USER` placeholder** → `User=portfolio` per Hugo's decision G.
3. **Spec I.2 didn't pass `--server.headless=true`** to Streamlit. Added — systemd-managed runs have no TTY, and without headless mode Streamlit prints an interactive first-run prompt to stdout.
4. **Spec I.3 didn't log to a persistent location.** Added `PTE_BACKUP_LOG` (defaults to `~/backup.log`) and `exec > >(tee -a ...)` so the log survives across service runs and is still captured by the journal.
5. **Spec I.4 had no `pte-backup.service`** — only the `.timer`. A timer without a named service relies on basename auto-matching, which is fragile. Added the service explicitly and wired `Unit=pte-backup.service` in the timer.
6. **Spec I.3 retention only handled daily** (spec's own note). Kept the 30-day daily prune; added placeholder `weekly/` `monthly/` dirs with a doc comment saying Phase 1 promotes snapshots. Avoids shipping half-implemented retention that silently drops data.

## Files created / modified

```
A  scripts/provision_vps.sh              (idempotent Ubuntu 24.04 bootstrap)
A  scripts/backup.sh                     (tar + cp + sqlite .backup + rclone + prune)
A  systemd/pte-streamlit.service         (User=portfolio, hardened)
A  systemd/pte-backup.service            (oneshot, runs backup.sh)
A  systemd/pte-backup.timer              (daily 03:30, Persistent)
A  tests/unit/test_devops.py             (23 tests)
A  docs/sprint_reports/11_devops.md      (this file)
```

## Verification

```bash
$ bash -n scripts/provision_vps.sh && echo OK
# OK
$ bash -n scripts/backup.sh && echo OK
# OK

$ systemd-analyze verify systemd/pte-streamlit.service systemd/pte-backup.service systemd/pte-backup.timer
# (no output — exit 0, all units parse cleanly)

$ uv run pytest
# 317 passed, 3 skipped in 9.37s

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 45 source files
```

**Manual VPS verification steps (for Hugo to run):**

```bash
# 1. Provisioning (should show mostly "skipped" since VPS already has these)
$ bash scripts/provision_vps.sh

# 2. Backup dry-run (after `pte setup` + at least one use)
$ bash scripts/backup.sh
$ ls -la backup/daily/$(date +%Y-%m-%d)/

# 3. Wire up systemd units
$ sudo ln -s /home/portfolio/workspace/portfolio-thesis-engine/systemd/pte-streamlit.service /etc/systemd/system/
$ sudo ln -s /home/portfolio/workspace/portfolio-thesis-engine/systemd/pte-backup.service /etc/systemd/system/
$ sudo ln -s /home/portfolio/workspace/portfolio-thesis-engine/systemd/pte-backup.timer /etc/systemd/system/
$ sudo systemctl daemon-reload
$ sudo systemctl enable --now pte-streamlit.service pte-backup.timer

# 4. Health
$ systemctl status pte-streamlit
$ systemctl list-timers pte-backup.timer
$ curl -I http://localhost:8501/      # → HTTP 200
```

## Tests passing / failing + coverage

All 317 unit tests pass (23 new devops tests + 294 from prior sprints); 3 integration tests skipped (gated).

DevOps artefacts live under `scripts/` and `systemd/` — not importable Python, so no coverage percentages. The 23 dedicated tests validate:

- Shebang present, executable bit set, `set -euo pipefail` used.
- `bash -n` passes on both scripts.
- `provision_vps.sh` uses all three detection primitives.
- `backup.sh` gates rclone sync, prunes 30-day daily, uses `.backup` for SQLite.
- Each systemd unit has `[Install]`.
- `pte-streamlit.service` uses `User=portfolio`, `Restart=on-failure`, explicit `WorkingDirectory`/`EnvironmentFile`.
- `pte-backup.timer` has `Persistent=true` and `Unit=pte-backup.service`.
- `systemd-analyze verify` exits 0 on all three units (run on the dev host).

| Project total | 1903 | 124 | 93 % |

## Problems encountered

1. **`shellcheck` not available in the dev environment.** `bash -n` catches syntax; style and subtle bugs would need shellcheck. Logged as a gap for whoever installs it next (trivial: `apt install shellcheck`); tests would then be easy to extend.
2. **`systemd-analyze verify` gives no output on success** — took a moment to realise exit 0 + silence is the expected shape. Test captures stdout/stderr for diagnosis on failure.
3. **No destructive operations required.** The whole sprint stays in build-and-verify territory; actual deployment is a Hugo-on-VPS step.

## Next step

**Batch 4 complete.** Remaining scope for Phase 0: Batch 5 will add
`tests/integration/test_smoke.py` (end-to-end against the real test
stack), ship documentation (`docs/architecture.md`, `docs/schemas.md`),
verify the final-check matrix in Parte L of the spec, and — per Hugo's
plan — wrap up Fase 0.
