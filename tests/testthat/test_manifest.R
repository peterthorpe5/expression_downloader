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
