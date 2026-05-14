

#' Build the default Parquet glob for the expression dataset.
#'
#' Uses the known partition structure written by the importer rather than a
#' recursive `**` glob. This is more portable across DuckDB, duckplyr and R
#' versions because some systems treat `**` as a literal pattern.
#'
#' @param parquet_dir Directory containing package Parquet outputs.
#' @return A glob matching all long-expression Parquet files.
build_expression_parquet_glob <- function(parquet_dir) {
  return(
    file.path(
      parquet_dir,
      "atlas_expression_long",
      "species_column=*",
      "experiment_accession=*",
      "*.parquet"
    )
  )
}


#' Count rows in a Parquet dataset through duckplyr.
#'
#' This is a lightweight validation helper for smoke-testing imported Parquet
#' files and DuckDB views without collecting the full expression table.
#'
#' @param parquet_glob Path or glob pointing to Parquet files.
#' @return Number of rows visible through duckplyr.
count_parquet_rows_duckplyr <- function(parquet_glob) {
  parquet_tbl <- duckplyr::read_parquet_duckdb(
    path = parquet_glob,
    prudence = "stingy",
    options = list(hive_partitioning = TRUE)
  )

  count_tbl <- parquet_tbl |>
    dplyr::summarise(n_rows = dplyr::n()) |>
    dplyr::collect()

  return(count_tbl$n_rows[[1L]])
}

#' Read long expression Parquet files through duckplyr.
#'
#' Returns a lazy duckplyr data frame. The full dataset is not collected into R
#' memory unless `collect()` is called later.
#'
#' @param parquet_glob Path or glob pointing to expression Parquet files.
#' @param prudence duckplyr prudence setting.
#' @return A lazy duckplyr data frame.
read_expression_parquet_duckplyr <- function(
  parquet_glob,
  prudence = "stingy"
) {
  expression_tbl <- duckplyr::read_parquet_duckdb(
    path = parquet_glob,
    prudence = prudence,
    options = list(hive_partitioning = TRUE)
  )

  return(expression_tbl)
}


#' Read a table from a DuckDB database file through duckplyr.
#'
#' This is the preferred function when the Shiny app is pointed at a materialised
#' DuckDB database file. It uses duckplyr's lazy DuckDB table reader.
#'
#' @param duckdb_path Path to a DuckDB database file.
#' @param table_name Name of the table or view to read.
#' @param schema DuckDB schema name.
#' @param prudence duckplyr prudence setting.
#' @return A lazy duckplyr data frame.
read_duckdb_table_duckplyr <- function(
  duckdb_path,
  table_name,
  schema = "main",
  prudence = "stingy"
) {
  if ("read_tbl_duckdb" %in% getNamespaceExports(ns = "duckplyr")) {
    duckplyr_tbl <- duckplyr::read_tbl_duckdb(
      path = duckdb_path,
      table_name = table_name,
      schema = schema,
      prudence = prudence
    )

    return(duckplyr_tbl)
  }

  safe_path <- normalise_sql_path(file_path = duckdb_path, must_work = TRUE)
  safe_schema <- stringr::str_replace_all(
    string = schema,
    pattern = "[^A-Za-z0-9_]",
    replacement = "_"
  )
  safe_table <- quote_duckdb_identifier(identifier = table_name)

  duckplyr::db_exec(
    sql = stringr::str_c(
      "ATTACH DATABASE '",
      safe_path,
      "' AS e3_expr_db (READ_ONLY)"
    )
  )

  duckplyr_tbl <- duckplyr::read_sql_duckdb(
    sql = stringr::str_c(
      "SELECT * FROM e3_expr_db.",
      safe_schema,
      ".",
      safe_table
    ),
    prudence = prudence
  )

  return(duckplyr_tbl)
}


#' Filter expression data using duckplyr/dplyr verbs.
#'
#' @param expression_tbl Lazy expression table.
#' @param species_column Optional species column to filter.
#' @param expression_unit Optional expression unit to filter.
#' @param minimum_expression Minimum expression value.
#' @return A lazy filtered expression table.
filter_expression_duckplyr <- function(
  expression_tbl,
  species_column = NULL,
  expression_unit = NULL,
  minimum_expression = NULL
) {
  filtered_tbl <- expression_tbl

  if (!is.null(species_column)) {
    filtered_tbl <- filtered_tbl |>
      dplyr::filter(.data$species_column == species_column)
  }

  if (!is.null(expression_unit)) {
    filtered_tbl <- filtered_tbl |>
      dplyr::filter(.data$expression_unit == expression_unit)
  }

  if (!is.null(minimum_expression)) {
    filtered_tbl <- filtered_tbl |>
      dplyr::filter(.data$expression_value >= minimum_expression)
  }

  return(filtered_tbl)
}


#' Materialise a DuckDB database from Parquet datasets.
#'
#' Creates a DuckDB database file with views pointing at the Parquet datasets.
#' The views use absolute Parquet paths so the database can be opened from a
#' Shiny app without loading all data into memory.
#'
#' @param duckdb_path Path to the DuckDB database file to create or update.
#' @param expression_parquet_glob Glob pointing to expression Parquet files.
#' @param alias_parquet_glob Optional glob pointing to alias Parquet files.
#' @param sample_parquet_glob Optional glob pointing to sample metadata Parquet files.
#' @return Invisibly returns the DuckDB path.
materialise_duckdb_views_from_parquet <- function(
  duckdb_path,
  expression_parquet_glob,
  alias_parquet_glob = NULL,
  sample_parquet_glob = NULL
) {
  ensure_directory(directory_path = dirname(duckdb_path))

  safe_duckdb_path <- normalise_sql_path(file_path = duckdb_path, must_work = FALSE)
  safe_expression_glob <- normalise_sql_path(
    file_path = expression_parquet_glob,
    must_work = FALSE
  )

  duckplyr::db_exec(
    sql = stringr::str_c(
      "ATTACH DATABASE '",
      safe_duckdb_path,
      "' AS e3_expression"
    )
  )

  duckplyr::db_exec(
    sql = stringr::str_c(
      "CREATE OR REPLACE VIEW e3_expression.atlas_expression_long AS ",
      "SELECT * FROM read_parquet('",
      safe_expression_glob,
      "', hive_partitioning = TRUE)"
    )
  )

  validation_tbl <- duckplyr::read_sql_duckdb(
    sql = "SELECT COUNT(*) AS n_rows FROM e3_expression.atlas_expression_long",
    prudence = "stingy"
  ) |>
    dplyr::collect()

  if (validation_tbl$n_rows[[1L]] == 0L) {
    warning(
      stringr::str_c(
        "DuckDB view atlas_expression_long was created but returned zero rows. ",
        "Check the Parquet glob: ",
        expression_parquet_glob
      ),
      call. = FALSE
    )
  }

  if (!is.null(alias_parquet_glob)) {
    safe_alias_glob <- normalise_sql_path(
      file_path = alias_parquet_glob,
      must_work = FALSE
    )

    duckplyr::db_exec(
      sql = stringr::str_c(
        "CREATE OR REPLACE VIEW e3_expression.gene_identifier_aliases AS ",
        "SELECT * FROM read_parquet('",
        safe_alias_glob,
        "', hive_partitioning = TRUE)"
      )
    )
  }

  if (!is.null(sample_parquet_glob)) {
    safe_sample_glob <- normalise_sql_path(
      file_path = sample_parquet_glob,
      must_work = FALSE
    )

    duckplyr::db_exec(
      sql = stringr::str_c(
        "CREATE OR REPLACE VIEW e3_expression.atlas_samples AS ",
        "SELECT * FROM read_parquet('",
        safe_sample_glob,
        "', hive_partitioning = TRUE)"
      )
    )
  }

  duckplyr::db_exec(sql = "DETACH e3_expression")

  return(invisible(duckdb_path))
}
