test_that("default expression Parquet glob uses fixed partition structure", {
  glob <- build_expression_parquet_glob(parquet_dir = "analysis/parquet")

  expect_match(glob, "species_column=\\*")
  expect_match(glob, "experiment_accession=\\*")
  expect_false(grepl("\\*\\*", glob))
})
