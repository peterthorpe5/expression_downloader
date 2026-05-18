"""Tests for Expression Atlas sample metadata importer."""

from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "inst"
    / "python"
    / "import_sample_metadata_to_parquet.py"
)

spec = importlib.util.spec_from_file_location("import_sample_metadata_to_parquet", SCRIPT)
metadata_importer = importlib.util.module_from_spec(spec)
sys.modules["import_sample_metadata_to_parquet"] = metadata_importer
assert spec.loader is not None
spec.loader.exec_module(metadata_importer)


class ImportSampleMetadataToParquetTests(unittest.TestCase):
    """Test SDRF/condensed-SDRF metadata handling."""

    def test_group_label_detection_from_group_column(self) -> None:
        """Atlas-style group labels should be detected from group columns."""

        row = {
            "Assay Group": "g1",
            "Characteristics[organism part]": "leaf",
        }
        self.assertEqual(metadata_importer.choose_sample_or_condition(row), "g1")

    def test_preferred_organism_part_is_extracted(self) -> None:
        """Common SDRF fields should flatten into preferred metadata columns."""

        row = {
            "Characteristics[organism part]": "root",
            "Factor Value[treatment]": "drought",
        }
        self.assertEqual(metadata_importer.get_preferred_value(row, "organism_part"), "root")
        self.assertEqual(metadata_importer.get_preferred_value(row, "treatment"), "drought")

    def test_jobs_are_built_from_download_manifest(self) -> None:
        """Only successful sample_metadata rows become metadata import jobs."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            manifest = tmp / "atlas_downloaded_files.tsv"
            fieldnames = [
                "species_column",
                "atlas_species_query",
                "experiment_accession",
                "file_type",
                "file_name",
                "url",
                "local_path",
                "action",
                "success",
                "local_bytes",
                "checked_at",
            ]
            with manifest.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
                writer.writeheader()
                writer.writerow(
                    {
                        "species_column": "Zea_mays",
                        "experiment_accession": "E-TEST-1",
                        "file_type": "sample_metadata",
                        "local_path": str(tmp / "metadata.tsv"),
                        "success": "true",
                    }
                )
                writer.writerow(
                    {
                        "species_column": "Zea_mays",
                        "experiment_accession": "E-TEST-1",
                        "file_type": "tpms",
                        "local_path": str(tmp / "tpms.tsv"),
                        "success": "true",
                    }
                )

            jobs = metadata_importer.build_jobs(downloaded_files_tsv=manifest)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].experiment_accession, "E-TEST-1")


    def test_make_closed_temp_path_is_writable_after_creation(self) -> None:
        """Temporary Parquet paths should not keep leaked descriptors open."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            created_paths = [
                metadata_importer.make_closed_temp_path(tmp, ".parquet.partial")
                for _ in range(25)
            ]

            for created_path in created_paths:
                created_path.write_text("ok", encoding="utf-8")
                self.assertTrue(created_path.exists())

    @unittest.skipIf(metadata_importer.pa is None, "pyarrow is not installed")
    def test_metadata_import_writes_rows(self) -> None:
        """A small metadata TSV should produce wide and long Parquet rows."""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            metadata = tmp / "metadata.tsv"
            metadata.write_text(
                "Assay Group\tCharacteristics[organism]\tCharacteristics[organism part]\tFactor Value[treatment]\n"
                "g1\tArabidopsis thaliana\tleaf\tcontrol\n"
                "g2\tArabidopsis thaliana\troot\tdrought\n",
                encoding="utf-8",
            )
            job = metadata_importer.MetadataJob(
                metadata_tsv=metadata,
                experiment_accession="E-TEST-1",
                species_column="Arabidopsis_thaliana",
            )

            result = metadata_importer.write_partitioned_metadata(
                job=job,
                output_dir=tmp,
                force=True,
            )

            self.assertTrue(result.success)
            self.assertEqual(result.metadata_records, 2)
            self.assertGreater(result.long_rows, 0)
            self.assertEqual(result.mapped_group_records, 2)


if __name__ == "__main__":
    unittest.main()
