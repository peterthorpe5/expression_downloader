#!/usr/bin/env bash
set -euo pipefail
python tests/python/test_discover_and_download_atlas.py
python tests/python/test_import_expression_to_parquet.py
