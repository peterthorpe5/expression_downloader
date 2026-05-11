#!/usr/bin/env bash
set -euo pipefail


# conda activate Go_analysis2

cd ~/data/2026_E3_protac/expression_downloader

Rscript inst/scripts/00_install_dependencies.R

R CMD INSTALL .

Rscript inst/scripts/run_all.R \
  --species_file=data/species.txt \
  --override_tsv=data/species_overrides.tsv \
  --output_dir=../analysis/expression_atlas \
  --force_download=false \
  --force_import=false \
  --create_duckdb=true

  # To add more species later, just edit:

  # data/species.txt 
  # to add the new species and its GTEx code (if available) and then re-run the above command with --force_download=false --force_import=false to skip the download and import steps for all species and just run the analyses on the new species.