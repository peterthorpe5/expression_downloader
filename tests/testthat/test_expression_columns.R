test_that("expression matrix columns are detected", {
  expression_tsv <- tempfile(fileext = ".tsv")
  readr::write_tsv(
    x = tibble::tibble(
      gene_id = c("gene1", "gene2"),
      gene_name = c("A", "B"),
      leaf = c(1.2, 3.4),
      root = c(0.1, 0.2)
    ),
    file = expression_tsv
  )

  column_info <- detect_expression_columns(expression_tsv = expression_tsv)

  expect_equal(column_info$gene_id_column, "gene_id")
  expect_equal(column_info$gene_name_column, "gene_name")
  expect_equal(column_info$expression_columns, c("leaf", "root"))
})
