#' Build candidate Expression Atlas FTP file URLs.
#'
#' Creates likely FTP file URLs for an Expression Atlas experiment. Not every
#' experiment has every file type, so these URLs are checked before download.
#'
#' @param experiment_accession Expression Atlas experiment accession.
#' @param species_column Internal species column name.
#' @return A tibble of candidate files.
build_atlas_ftp_manifest <- function(experiment_accession, species_column) {
  base_url <- stringr::str_c(
    "https://ftp.ebi.ac.uk/pub/databases/microarray/data/atlas/experiments/",
    experiment_accession,
    "/"
  )

  file_types <- c(
    "tpms",
    "fpkms",
    "transcript_tpms",
    "sample_metadata",
    "analysis_methods",
    "r_object"
  )

  file_names <- c(
    stringr::str_c(experiment_accession, "-tpms.tsv"),
    stringr::str_c(experiment_accession, "-fpkms.tsv"),
    stringr::str_c(experiment_accession, "-transcript_tpms.tsv"),
    stringr::str_c(experiment_accession, ".condensed-sdrf.tsv"),
    stringr::str_c(experiment_accession, "-analysis-methods.tsv"),
    stringr::str_c(experiment_accession, "-atlasExperimentSummary.Rdata")
  )

  manifest_tbl <- tibble::tibble(
    experiment_accession = experiment_accession,
    species_column = species_column,
    file_type = file_types,
    file_name = file_names
  ) |>
    dplyr::mutate(url = stringr::str_c(base_url, .data$file_name))

  return(manifest_tbl)
}


#' Check whether a remote file appears to exist and is non-empty.
#'
#' Uses an HTTP HEAD request first. If the server does not provide a useful
#' content length, the function attempts a one-byte ranged GET request as a
#' fallback. This avoids downloading large files just to check availability.
#'
#' @param url Remote file URL.
#' @param timeout_seconds Request timeout in seconds.
#' @return A tibble containing URL availability, status code and size metadata.
check_remote_file <- function(url, timeout_seconds = 30L) {
  head_response <- tryCatch(
    expr = httr2::request(base_url = url) |>
      httr2::req_method(method = "HEAD") |>
      httr2::req_timeout(seconds = timeout_seconds) |>
      httr2::req_perform(),
    error = function(error) {
      return(NULL)
    }
  )

  if (!is.null(head_response)) {
    status_code <- httr2::resp_status(resp = head_response)
    content_length <- httr2::resp_header(
      resp = head_response,
      header = "content-length"
    )
    content_length <- suppressWarnings(as.numeric(content_length))

    if (status_code < 400L && !is.na(content_length) && content_length > 0) {
      return(
        tibble::tibble(
          url = url,
          remote_exists = TRUE,
          remote_non_empty = TRUE,
          status_code = status_code,
          remote_bytes = content_length,
          check_method = "HEAD"
        )
      )
    }

    if (status_code >= 400L) {
      return(
        tibble::tibble(
          url = url,
          remote_exists = FALSE,
          remote_non_empty = FALSE,
          status_code = status_code,
          remote_bytes = content_length,
          check_method = "HEAD"
        )
      )
    }
  }

  range_response <- tryCatch(
    expr = httr2::request(base_url = url) |>
      httr2::req_headers(Range = "bytes=0-0") |>
      httr2::req_timeout(seconds = timeout_seconds) |>
      httr2::req_perform(),
    error = function(error) {
      return(NULL)
    }
  )

  if (is.null(range_response)) {
    return(
      tibble::tibble(
        url = url,
        remote_exists = FALSE,
        remote_non_empty = FALSE,
        status_code = NA_integer_,
        remote_bytes = NA_real_,
        check_method = "GET_RANGE_FAILED"
      )
    )
  }

  status_code <- httr2::resp_status(resp = range_response)
  body_size <- length(httr2::resp_body_raw(resp = range_response))

  return(
    tibble::tibble(
      url = url,
      remote_exists = status_code < 400L,
      remote_non_empty = status_code < 400L && body_size > 0L,
      status_code = status_code,
      remote_bytes = NA_real_,
      check_method = "GET_RANGE"
    )
  )
}


#' Check remote availability for a file manifest.
#'
#' @param manifest_tbl Candidate file manifest.
#' @return Manifest with remote status columns added.
check_manifest_remotes <- function(manifest_tbl) {
  checked_tbl <- manifest_tbl |>
    dplyr::mutate(
      remote_status = purrr::map(
        .x = .data$url,
        .f = function(url) {
          check_remote_file(url = url) |>
            dplyr::select(-.data$url)
        }
      )
    ) |>
    tidyr::unnest(cols = "remote_status")

  return(checked_tbl)
}


#' Download a remote file only when required.
#'
#' Skips download if the local file already exists and is non-empty. Otherwise,
#' checks the remote file and downloads it only if the remote file exists and is
#' non-empty. Downloads are first written to a temporary partial file and then
#' moved into place after size validation.
#'
#' @param url Remote file URL.
#' @param local_path Local output path.
#' @param force Logical value controlling whether to overwrite usable files.
#' @param minimum_bytes Minimum acceptable file size in bytes.
#' @return A tibble describing the download status.
download_if_needed <- function(
  url,
  local_path,
  force = FALSE,
  minimum_bytes = 1L
) {
  ensure_directory(directory_path = dirname(local_path))

  if (!force && local_file_is_usable(
    file_path = local_path,
    minimum_bytes = minimum_bytes
  )) {
    return(
      tibble::tibble(
        url = url,
        local_path = local_path,
        action = "skipped_existing_local_file",
        success = TRUE,
        local_bytes = file.info(local_path)$size
      )
    )
  }

  remote_status <- check_remote_file(url = url)

  if (!remote_status$remote_exists[[1L]] || !remote_status$remote_non_empty[[1L]]) {
    return(
      tibble::tibble(
        url = url,
        local_path = local_path,
        action = "skipped_remote_missing_or_empty",
        success = FALSE,
        local_bytes = NA_real_
      )
    )
  }

  temporary_path <- stringr::str_c(local_path, ".partial")

  download_result <- tryCatch(
    expr = {
      utils::download.file(
        url = url,
        destfile = temporary_path,
        mode = "wb",
        quiet = TRUE
      )
      TRUE
    },
    error = function(error) {
      FALSE
    }
  )

  if (!download_result) {
    return(
      tibble::tibble(
        url = url,
        local_path = local_path,
        action = "download_failed",
        success = FALSE,
        local_bytes = NA_real_
      )
    )
  }

  if (!local_file_is_usable(
    file_path = temporary_path,
    minimum_bytes = minimum_bytes
  )) {
    unlink(x = temporary_path)

    return(
      tibble::tibble(
        url = url,
        local_path = local_path,
        action = "downloaded_file_empty",
        success = FALSE,
        local_bytes = NA_real_
      )
    )
  }

  file.rename(from = temporary_path, to = local_path)

  return(
    tibble::tibble(
      url = url,
      local_path = local_path,
      action = "downloaded",
      success = TRUE,
      local_bytes = file.info(local_path)$size
    )
  )
}


#' Download all available files in a checked manifest.
#'
#' @param checked_manifest_tbl Manifest after `check_manifest_remotes()`.
#' @param force Logical value controlling whether to overwrite usable files.
#' @return Download log tibble.
download_checked_manifest <- function(checked_manifest_tbl, force = FALSE) {
  downloadable_tbl <- checked_manifest_tbl |>
    dplyr::filter(.data$remote_exists) |>
    dplyr::filter(.data$remote_non_empty)

  if (nrow(downloadable_tbl) == 0L) {
    return(
      tibble::tibble(
        url = character(),
        local_path = character(),
        action = character(),
        success = logical(),
        local_bytes = numeric()
      )
    )
  }

  download_log_tbl <- purrr::pmap_dfr(
    .l = list(
      url = downloadable_tbl$url,
      local_path = downloadable_tbl$local_path
    ),
    .f = function(url, local_path) {
      download_if_needed(
        url = url,
        local_path = local_path,
        force = force,
        minimum_bytes = 1L
      )
    }
  )

  return(download_log_tbl)
}
