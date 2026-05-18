# v0.3.3 patch notes

This patch fixes the duckplyr query helper used after DuckDB view creation.

The previous helper tried to use `duckplyr::read_tbl_duckdb()` when available.
On some duckplyr versions this interpreted the DuckDB file stem as a schema name,
leading to errors such as:

```text
Table with name "e3_expression.atlas_expression_long" does not exist because
schema "e3_expression" does not exist.
```

The helper now always attaches the DuckDB file explicitly in read-only mode and
queries `attached_database.main.<table_or_view>` via `duckplyr::read_sql_duckdb()`.
This keeps the query layer lazy and avoids loading data into R memory.
