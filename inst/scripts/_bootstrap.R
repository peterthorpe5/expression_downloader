#!/usr/bin/env Rscript

# Source package functions when running scripts from an unpacked source tree.
# If the package is already installed, use the installed package instead.

if (requireNamespace(package = "E3AtlasDuckplyr", quietly = TRUE)) {
  library(package = "E3AtlasDuckplyr", character.only = TRUE)
} else {
  cmd_args <- commandArgs(trailingOnly = FALSE)
  file_arg <- cmd_args[grep(pattern = "^--file=", x = cmd_args)]

  if (length(file_arg) > 0L) {
    script_path <- normalizePath(
      path = sub(pattern = "^--file=", replacement = "", x = file_arg[[1L]]),
      winslash = "/",
      mustWork = FALSE
    )
  } else {
    script_path <- normalizePath(path = getwd(), winslash = "/", mustWork = FALSE)
  }

  candidate_roots <- c(
    normalizePath(path = getwd(), winslash = "/", mustWork = FALSE),
    normalizePath(path = file.path(dirname(script_path), "..", ".."), winslash = "/", mustWork = FALSE)
  )

  matching_roots <- candidate_roots[file.exists(file.path(candidate_roots, "DESCRIPTION"))]

  if (length(matching_roots) == 0L) {
    stop("Could not find package root. Run scripts from the unpacked package directory.", call. = FALSE)
  }

  package_root <- matching_roots[[1L]]

  r_files <- list.files(
    path = file.path(package_root, "R"),
    pattern = "[.]R$",
    full.names = TRUE
  )

  for (r_file in sort(r_files)) {
    source(file = r_file)
  }
}
