#!/usr/bin/env Rscript

cran_packages <- c(
  "dplyr",
  "duckplyr",
  "fs",
  "httr2",
  "purrr",
  "readr",
  "rlang",
  "stringr",
  "tibble",
  "tidyr",
  "testthat"
)

missing_cran_packages <- cran_packages[!vapply(
  X = cran_packages,
  FUN = requireNamespace,
  FUN.VALUE = logical(length = 1L),
  quietly = TRUE
)]

if (length(missing_cran_packages) > 0L) {
  install.packages(pkgs = missing_cran_packages)
}

if (!requireNamespace(package = "BiocManager", quietly = TRUE)) {
  install.packages(pkgs = "BiocManager")
}

if (!requireNamespace(package = "ExpressionAtlas", quietly = TRUE)) {
  message("Installing optional Bioconductor package ExpressionAtlas.")
  BiocManager::install(pkgs = "ExpressionAtlas", ask = FALSE, update = FALSE)
}

message("Dependency installation step finished.")
