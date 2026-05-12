# Python-first Expression Atlas workflow

This package version moves Expression Atlas web discovery and downloading into
Python. R is still used for the part your boss wants in R: converting downloaded
TPM/FPKM matrices into Parquet/DuckDB resources for `duckplyr` and Shiny.

## Why this exists

The R `ExpressionAtlas`/ArrayExpress XML search route can be fragile on clusters
because the endpoint may return XML, HTML, text errors, or proxy messages. The
Python workflow does not rely on strict XML parsing. It extracts candidate
Expression Atlas accessions, validates them by checking for real TPM/FPKM files
on the EBI FTP site, then downloads only experiments with usable expression
matrices.

## Recommended run

Run from the package root directory.

```bash
conda activate expression_downloaderR

R CMD INSTALL .
Rscript inst/scripts/08_run_tests.R
./inst/scripts/09_run_python_tests.sh

./inst/scripts/run_python_first_then_r.sh \
  --species_file=data/species.txt \
  --override_tsv=data/species_overrides.tsv \
  --output_dir=../analysis/expression_atlas_python \
  --force_download=false \
  --force_import=false \
  --create_duckdb=true \
  --timeout_seconds=30 \
  --retries=2
```

For a small smoke test, add:

```bash
  --max_experiments_per_species=20
```

## Python-only discovery/download step

```bash
./inst/scripts/02_python_discover_download_atlas.sh \
  --species_file data/species.txt \
  --override_tsv data/species_overrides.tsv \
  --output_dir ../analysis/expression_atlas_python \
  --force_download false \
  --timeout_seconds 30 \
  --retries 2
```

This writes:

```text
../analysis/expression_atlas_python/manifests/species_registry.tsv
../analysis/expression_atlas_python/manifests/atlas_candidate_experiments.tsv
../analysis/expression_atlas_python/manifests/atlas_checked_file_manifest.tsv
../analysis/expression_atlas_python/manifests/atlas_expression_matrix_availability.tsv
../analysis/expression_atlas_python/manifests/atlas_selected_checked_file_manifest.tsv
../analysis/expression_atlas_python/manifests/atlas_downloaded_files.tsv
../analysis/expression_atlas_python/manifests/atlas_python_summary.tsv
../analysis/expression_atlas_python/manifests/python_atlas_pipeline.log
```

## R import step after Python download

```bash
Rscript inst/scripts/04_import_expression_to_parquet.R \
  --downloaded_files_tsv=../analysis/expression_atlas_python/manifests/atlas_downloaded_files.tsv \
  --output_dir=../analysis/expression_atlas_python \
  --force_import=false

Rscript inst/scripts/06_create_duckdb_views.R \
  --output_dir=../analysis/expression_atlas_python \
  --duckdb_path=../analysis/expression_atlas_python/e3_expression.duckdb
```

## Checking results

```bash
cat ../analysis/expression_atlas_python/manifests/atlas_python_summary.tsv

find ../analysis/expression_atlas_python/downloads \
  \( -name '*tpms.tsv' -o -name '*fpkms.tsv' \) \
  | head

find ../analysis/expression_atlas_python/parquet -type f | head
```

## Adding species later

Edit:

```text
data/species.txt
```

Then rerun the same command with `--force_download=false`. Existing non-empty
files will be skipped.
