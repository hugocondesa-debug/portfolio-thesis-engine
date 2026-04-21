#!/usr/bin/env bash
# Daily backup for Portfolio Thesis Engine — runs under the
# pte-backup.service systemd unit.
#
# Captures: YAMLs (tar.gz), DuckDB file, SQLite DB via `.backup` to get a
# consistent copy even if the engine is writing. Optionally syncs the
# daily bundle to a remote rclone destination configured as `backup:`.
#
# Retention:
#   daily/   — keep last 30 days
#   weekly/  — stub (implemented by the timer catch-up, see I.4)
#   monthly/ — stub
#
# Log: ~/backup.log (appended).

set -euo pipefail

REPO_ROOT="${PTE_REPO_ROOT:-$HOME/workspace/portfolio-thesis-engine}"
BACKUP_ROOT="$REPO_ROOT/backup"
DATA_DIR="$REPO_ROOT/data"
TODAY="$(date +%Y-%m-%d)"
BACKUP_PATH="$BACKUP_ROOT/daily/$TODAY"
LOG_FILE="${PTE_BACKUP_LOG:-$HOME/backup.log}"

# Redirect all output to the log while still streaming to stdout (systemd
# journal picks up stdout via the service's default Logs=journal).
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== pte-backup $(date --iso-8601=seconds) ==="

mkdir -p "$BACKUP_PATH"

# 1. YAMLs → tar.gz (preserves tree and symlinks).
if [ -d "$DATA_DIR/yamls" ]; then
    echo "[1/4] YAMLs → yamls.tar.gz"
    tar -czf "$BACKUP_PATH/yamls.tar.gz" -C "$DATA_DIR" yamls/
else
    echo "[1/4] YAMLs: $DATA_DIR/yamls absent — skipping"
fi

# 2. DuckDB.
if [ -f "$DATA_DIR/timeseries.duckdb" ]; then
    echo "[2/4] DuckDB → timeseries.duckdb"
    cp -a "$DATA_DIR/timeseries.duckdb" "$BACKUP_PATH/timeseries.duckdb"
else
    echo "[2/4] DuckDB: absent — skipping"
fi

# 3. SQLite via .backup (atomic under concurrent writes).
if [ -f "$DATA_DIR/metadata.sqlite" ]; then
    echo "[3/4] SQLite → metadata.sqlite"
    sqlite3 "$DATA_DIR/metadata.sqlite" ".backup $BACKUP_PATH/metadata.sqlite"
else
    echo "[3/4] SQLite: absent — skipping"
fi

# 4. Offsite sync (gated on rclone remote).
if command -v rclone >/dev/null 2>&1 && rclone listremotes 2>/dev/null | grep -q '^backup:$'; then
    echo "[4/4] rclone sync → backup:portfolio-thesis-engine/$TODAY"
    rclone sync "$BACKUP_PATH" "backup:portfolio-thesis-engine/$TODAY"
else
    echo "[4/4] rclone 'backup:' remote not configured — skipping offsite sync"
fi

# ---- Retention sweep ------------------------------------------------------
echo "Retention sweep:"
# Daily: 30 days.
removed_daily=$(find "$BACKUP_ROOT/daily" -maxdepth 1 -mindepth 1 -type d -mtime +30 -print -exec rm -rf {} + 2>/dev/null | wc -l)
echo "  daily > 30d pruned: $removed_daily"

# Weekly / monthly tiers are placeholders for Phase 1 — directories are
# created so operators see the expected layout, but no promotion logic
# runs here yet.
mkdir -p "$BACKUP_ROOT/weekly" "$BACKUP_ROOT/monthly"
echo "  weekly/monthly: placeholders only (Phase 1 promotes snapshots)"

echo "Backup complete: $BACKUP_PATH"
