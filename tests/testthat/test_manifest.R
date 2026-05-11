test_that("Expression Atlas FTP manifest has expected files", {
  manifest_tbl <- build_atlas_ftp_manifest(
    experiment_accession = "E-MTAB-5915",
    species_column = "Zea_mays"
  )

  expect_equal(nrow(manifest_tbl), 6L)
  expect_true("tpms" %in% manifest_tbl$file_type)
  expect_true("fpkms" %in% manifest_tbl$file_type)
  expect_true("sample_metadata" %in% manifest_tbl$file_type)
  expect_true(any(grepl(pattern = "E-MTAB-5915-tpms.tsv", x = manifest_tbl$file_name)))
})


test_that("remote manifest checks keep one URL column", {
  mock_remote_checker <- function(url) {
    tibble::tibble(
      url = url,
      remote_exists = TRUE,
      remote_non_empty = TRUE,
      status_code = 200L,
      remote_bytes = 10,
      check_method = "mock"
    )
  }

  manifest_tbl <- tibble::tibble(
    experiment_accession = "E-TEST-1",
    species_column = "Arabidopsis_thaliana",
    file_type = "tpms",
    file_name = "E-TEST-1-tpms.tsv",
    url = "https://example.org/E-TEST-1-tpms.tsv",
    local_path = tempfile(fileext = ".tsv")
  )

  checked_tbl <- check_manifest_remotes(
    manifest_tbl = manifest_tbl,
    remote_checker = mock_remote_checker
  )

  expect_equal(sum(names(checked_tbl) == "url"), 1L)
  expect_true("remote_exists" %in% names(checked_tbl))
  expect_true(checked_tbl$remote_exists[[1L]])
})
