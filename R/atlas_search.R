#' Normalise Expression Atlas search results.
#'
#' @param result_tbl Raw result tibble from `ExpressionAtlas::searchAtlasExperiments()`.
#' @param species_column Internal species column name.
#' @param atlas_species_query Species query used for Atlas.
#' @return Normalised candidate experiment tibble.
normalise_atlas_search_results <- function(
  result_tbl,
  species_column,
  atlas_species_query
) {
  if (nrow(result_tbl) == 0L) {
    return(
      tibble::tibble(
        experiment_accession = character(),
        species_column = character(),
        atlas_species_query = character(),
        search_term = character()
      )
    )
  }

  column_names <- names(result_tbl)
  accession_column <- column_names[
    stringr::str_detect(
      string = stringr::str_to_lower(column_names),
      pattern = "^accession$|experiment.*accession"
    )
  ][[1L]]

  if (is.na(accession_column)) {
    stop("Could not identify an accession column in Atlas search results.", call. = FALSE)
  }

  normalised_tbl <- result_tbl |>
    dplyr::rename(experiment_accession = dplyr::all_of(accession_column)) |>
    dplyr::mutate(
      species_column = species_column,
      atlas_species_query = atlas_species_query
    ) |>
    dplyr::distinct(.data$experiment_accession, .keep_all = TRUE)

  return(normalised_tbl)
}


#' Search Expression Atlas for RNA-seq-like experiments for one species.
#'
#' Uses the Bioconductor ExpressionAtlas package when available. The result is
#' deliberately treated as a candidate list because Atlas metadata can vary by
#' species and release.
#'
#' @param atlas_species_query Scientific species name to search.
#' @param species_column Internal species column name.
#' @param search_terms Character vector of search terms.
#' @return A tibble of candidate experiment records.
search_atlas_species <- function(
  atlas_species_query,
  species_column,
  search_terms = c("RNA-seq", "RNA sequencing", "transcriptome", "baseline")
) {
  if (!requireNamespace(package = "ExpressionAtlas", quietly = TRUE)) {
    warning(
      stringr::str_c(
        "ExpressionAtlas is not installed. Returning no search results for ",
        atlas_species_query,
        "."
      ),
      call. = FALSE
    )

    return(
      tibble::tibble(
        experiment_accession = character(),
        species_column = character(),
        atlas_species_query = character(),
        search_term = character()
      )
    )
  }

  result_tbl <- purrr::map_dfr(
    .x = search_terms,
    .f = function(search_term) {
      result <- tryCatch(
        expr = ExpressionAtlas::searchAtlasExperiments(
          properties = search_term,
          species = atlas_species_query
        ),
        error = function(error) {
          return(NULL)
        }
      )

      if (is.null(result)) {
        return(tibble::tibble())
      }

      tibble::as_tibble(result) |>
        dplyr::mutate(search_term = search_term)
    }
  )

  if (nrow(result_tbl) == 0L) {
    return(
      tibble::tibble(
        experiment_accession = character(),
        species_column = character(),
        atlas_species_query = character(),
        search_term = character()
      )
    )
  }

  normalised_tbl <- normalise_atlas_search_results(
    result_tbl = result_tbl,
    species_column = species_column,
    atlas_species_query = atlas_species_query
  )

  return(normalised_tbl)
}


#' Search Expression Atlas for all included species in a registry.
#'
#' @param species_registry_tbl Species registry tibble.
#' @return Candidate experiment tibble.
search_atlas_from_species_registry <- function(species_registry_tbl) {
  included_species_tbl <- species_registry_tbl |>
    dplyr::filter(.data$include)

  if (nrow(included_species_tbl) == 0L) {
    return(
      tibble::tibble(
        experiment_accession = character(),
        species_column = character(),
        atlas_species_query = character(),
        search_term = character()
      )
    )
  }

  experiment_tbl <- purrr::pmap_dfr(
    .l = list(
      atlas_species_query = included_species_tbl$atlas_species_query,
      species_column = included_species_tbl$species_column
    ),
    .f = function(atlas_species_query, species_column) {
      message(
        stringr::str_c(
          "Searching Expression Atlas for ",
          species_column,
          " using query '",
          atlas_species_query,
          "'"
        )
      )

      search_atlas_species(
        atlas_species_query = atlas_species_query,
        species_column = species_column
      )
    }
  ) |>
    dplyr::distinct(
      .data$experiment_accession,
      .data$species_column,
      .keep_all = TRUE
    )

  return(experiment_tbl)
}


#' Read a manually curated experiment TSV.
#'
#' The TSV must contain `species_column` and `experiment_accession` columns. This
#' is useful when Expression Atlas searching is unavailable or when experiments
#' have been chosen by hand.
#'
#' @param experiment_tsv Path to manually curated experiment TSV.
#' @return Candidate experiment tibble.
read_manual_experiments <- function(experiment_tsv) {
  if (is.null(experiment_tsv) || !file.exists(experiment_tsv)) {
    return(
      tibble::tibble(
        experiment_accession = character(),
        species_column = character(),
        atlas_species_query = character(),
        search_term = character()
      )
    )
  }

  experiment_tbl <- readr::read_tsv(
    file = experiment_tsv,
    show_col_types = FALSE
  )

  required_columns <- c("species_column", "experiment_accession")
  missing_columns <- setdiff(x = required_columns, y = names(experiment_tbl))

  if (length(missing_columns) > 0L) {
    stop(
      stringr::str_c(
        "Manual experiment TSV is missing required columns: ",
        stringr::str_c(missing_columns, collapse = ", ")
      ),
      call. = FALSE
    )
  }

  if (!"atlas_species_query" %in% names(experiment_tbl)) {
    experiment_tbl <- experiment_tbl |>
      dplyr::mutate(atlas_species_query = NA_character_)
  }

  if (!"search_term" %in% names(experiment_tbl)) {
    experiment_tbl <- experiment_tbl |>
      dplyr::mutate(search_term = "manual")
  }

  return(experiment_tbl)
}
