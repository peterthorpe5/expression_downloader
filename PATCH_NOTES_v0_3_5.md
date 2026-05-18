# Patch notes v0.3.5

This patch improves the Expression Atlas sample metadata layer.

Changes:

- Chooses one preferred metadata file per species/experiment.
- Prefers `*.condensed-sdrf.tsv` over full `*.sdrf.txt` files because condensed SDRFs are more likely to contain Atlas expression group labels such as `g1`.
- Stops later full SDRF files from overwriting better group-level metadata for the same experiment.
- Collapses duplicate wide metadata records to one row per non-empty `sample_or_condition`.
- Excludes blank sample/condition keys from the joinable metadata view.
- Adds `atlas_sample_metadata_wide_joinable` DuckDB view.
- Adds Python unit tests for metadata file preference and duplicate group collapse.

Existing expression Parquet files do not need to be rebuilt. Rebuild the sample metadata Parquet files with `--force_import=true`, then recreate DuckDB views.
