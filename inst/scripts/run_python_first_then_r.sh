#!/usr/bin/env bash
set -euo pipefail

SPECIES_FILE="data/species.txt"
OVERRIDE_TSV="data/species_overrides.tsv"
OUTPUT_DIR="../analysis/expression_atlas_python"
FORCE_DOWNLOAD="false"
FORCE_IMPORT="false"
CREATE_DUCKDB="true"
TIMEOUT_SECONDS="30"
RETRIES="2"
MAX_EXPERIMENTS_PER_SPECIES="0"
DISCOVERY_BACKEND="ftp_scan"
FTP_SCAN_MAX_ACCESSIONS="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --species_file=*) SPECIES_FILE="${1#*=}"; shift ;;
    --species_file) SPECIES_FILE="$2"; shift 2 ;;
    --override_tsv=*) OVERRIDE_TSV="${1#*=}"; shift ;;
    --override_tsv) OVERRIDE_TSV="$2"; shift 2 ;;
    --output_dir=*) OUTPUT_DIR="${1#*=}"; shift ;;
    --output_dir) OUTPUT_DIR="$2"; shift 2 ;;
    --force_download=*) FORCE_DOWNLOAD="${1#*=}"; shift ;;
    --force_download) FORCE_DOWNLOAD="$2"; shift 2 ;;
    --force_import=*) FORCE_IMPORT="${1#*=}"; shift ;;
    --force_import) FORCE_IMPORT="$2"; shift 2 ;;
    --create_duckdb=*) CREATE_DUCKDB="${1#*=}"; shift ;;
    --create_duckdb) CREATE_DUCKDB="$2"; shift 2 ;;
    --timeout_seconds=*) TIMEOUT_SECONDS="${1#*=}"; shift ;;
    --timeout_seconds) TIMEOUT_SECONDS="$2"; shift 2 ;;
    --retries=*) RETRIES="${1#*=}"; shift ;;
    --retries) RETRIES="$2"; shift 2 ;;
    --max_experiments_per_species=*) MAX_EXPERIMENTS_PER_SPECIES="${1#*=}"; shift ;;
    --max_experiments_per_species) MAX_EXPERIMENTS_PER_SPECIES="$2"; shift 2 ;;
    --discovery_backend=*) DISCOVERY_BACKEND="${1#*=}"; shift ;;
    --discovery_backend) DISCOVERY_BACKEND="$2"; shift 2 ;;
    --ftp_scan_max_accessions=*) FTP_SCAN_MAX_ACCESSIONS="${1#*=}"; shift ;;
    --ftp_scan_max_accessions) FTP_SCAN_MAX_ACCESSIONS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

"${SCRIPT_DIR}/02_python_discover_download_atlas.sh" \
  --species_file "${SPECIES_FILE}" \
  --override_tsv "${OVERRIDE_TSV}" \
  --output_dir "${OUTPUT_DIR}" \
  --force_download "${FORCE_DOWNLOAD}" \
  --timeout_seconds "${TIMEOUT_SECONDS}" \
  --retries "${RETRIES}" \
  --max_experiments_per_species "${MAX_EXPERIMENTS_PER_SPECIES}" \
  --discovery_backend "${DISCOVERY_BACKEND}" \
  --ftp_scan_max_accessions "${FTP_SCAN_MAX_ACCESSIONS}"

Rscript "${SCRIPT_DIR}/04_import_expression_to_parquet.R" \
  --downloaded_files_tsv="${OUTPUT_DIR}/manifests/atlas_downloaded_files.tsv" \
  --output_dir="${OUTPUT_DIR}" \
  --force_import="${FORCE_IMPORT}"

if [[ "${CREATE_DUCKDB}" == "true" || "${CREATE_DUCKDB}" == "TRUE" || "${CREATE_DUCKDB}" == "1" ]]; then
  Rscript "${SCRIPT_DIR}/06_create_duckdb_views.R" \
    --output_dir="${OUTPUT_DIR}" \
    --duckdb_path="${OUTPUT_DIR}/e3_expression.duckdb"
fi
