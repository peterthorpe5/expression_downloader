#!/usr/bin/env python3
"""Import Expression Atlas SDRF/sample metadata into Parquet.

The Expression Atlas expression matrices use compact sample/condition labels
such as ``g1`` and ``g10``. The accompanying SDRF or condensed-SDRF files hold
metadata describing those groups or the underlying assays. This script imports
those metadata files into two Parquet datasets:

``atlas_sample_metadata_long``
    One row per metadata field/value.

``atlas_sample_metadata_wide``
    One row per metadata record with commonly useful fields flattened where
    possible.

The importer is deliberately permissive because Atlas metadata differ between
experiments. It does not require a perfect group mapping; instead it preserves
all metadata and records any detected group/sample label as ``sample_or_condition``.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = None
    pq = None

TRUE_VALUES = {"true", "t", "yes", "y", "1"}
FALSE_VALUES = {"false", "f", "no", "n", "0", ""}
METADATA_FILE_TYPES = {"sample_metadata"}
GROUP_PATTERN = re.compile(r"^g\d+$", flags=re.IGNORECASE)

PREFERRED_FIELDS = {
    "organism": (
        "characteristics[organism]",
        "organism",
    ),
    "organism_part": (
        "characteristics[organism part]",
        "characteristics[organism_part]",
        "organism part",
        "organism_part",
        "factor value[organism part]",
    ),
    "developmental_stage": (
        "characteristics[developmental stage]",
        "developmental stage",
        "developmental_stage",
        "factor value[developmental stage]",
    ),
    "genotype": (
        "characteristics[genotype]",
        "genotype",
        "factor value[genotype]",
    ),
    "cultivar": (
        "characteristics[cultivar]",
        "cultivar",
        "characteristics[variety]",
        "variety",
    ),
    "treatment": (
        "characteristics[treatment]",
        "treatment",
        "factor value[treatment]",
        "factor value[compound]",
    ),
    "condition": (
        "factor value[condition]",
        "condition",
        "factor value[disease]",
        "factor value[phenotype]",
    ),
    "assay_name": (
        "assay name",
        "assay_name",
    ),
    "source_name": (
        "source name",
        "source_name",
    ),
    "sample_name": (
        "sample name",
        "sample_name",
    ),
}

GROUP_COLUMN_HINTS = (
    "assay group",
    "sample group",
    "atlas group",
    "group",
    "factor value",
    "comment[ea",
    "comment[atlas",
)


@dataclass(frozen=True)
class MetadataJob:
    """A single metadata import job."""

    metadata_tsv: Path
    experiment_accession: str
    species_column: str
    source_database: str = "ExpressionAtlas"


@dataclass(frozen=True)
class MetadataResult:
    """Summary of one metadata import."""

    metadata_tsv: Path
    experiment_accession: str
    species_column: str
    action: str
    success: bool
    metadata_records: int
    long_rows: int
    mapped_group_records: int
    message: str


def require_pyarrow() -> None:
    """Stop with a clear message if pyarrow is unavailable."""

    if pa is None or pq is None:
        raise SystemExit(
            "Missing Python dependency: pyarrow. Install it with:\n"
            "  mamba install -c conda-forge pyarrow"
        )


def parse_bool(value: object, default: bool = False) -> bool:
    """Convert common text values to boolean."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return default


def open_text(path: Path):
    """Open a plain or gzipped text file."""

    if str(path).endswith(".gz"):
        return gzip.open(path, mode="rt", encoding="utf-8", newline="")
    return path.open(mode="r", encoding="utf-8", newline="")




def make_closed_temp_path(parent_dir: Path, suffix: str) -> Path:
    """Create a temporary path and immediately close the file descriptor.

    ``tempfile.mkstemp()`` returns an open file descriptor. If that descriptor
    is not closed, long metadata imports can hit the operating-system open-file
    limit after hundreds of experiments. This helper keeps the robust unique
    temporary-path behaviour while avoiding descriptor leaks.
    """

    file_descriptor, temporary_name = tempfile.mkstemp(
        suffix=suffix,
        dir=str(parent_dir),
    )
    os.close(file_descriptor)
    return Path(temporary_name)

def normalise_header(value: str) -> str:
    """Normalise a metadata header for matching."""

    text = value.strip().strip('"').strip("'")
    text = re.sub(r"\s+", " ", text)
    return text


def normalise_key(value: str) -> str:
    """Return a lower-case matching key."""

    return normalise_header(value).lower()


def make_unique(names: Iterable[str]) -> list[str]:
    """Return unique column names while preserving order."""

    seen: dict[str, int] = {}
    unique: list[str] = []
    for name in names:
        clean = normalise_header(name)
        if clean == "":
            clean = "unnamed_column"
        count = seen.get(clean, 0) + 1
        seen[clean] = count
        if count == 1:
            unique.append(clean)
        else:
            unique.append(f"{clean}_{count}")
    return unique


def is_group_value(value: str) -> bool:
    """Return true when a value looks like an Atlas group label."""

    return bool(GROUP_PATTERN.match(value.strip()))


def choose_sample_or_condition(row: dict[str, str]) -> str:
    """Infer the compact expression group/sample label for a metadata row."""

    for key, value in row.items():
        key_lower = normalise_key(key)
        if any(hint in key_lower for hint in GROUP_COLUMN_HINTS) and is_group_value(value):
            return value.strip()

    for value in row.values():
        if is_group_value(value):
            return value.strip()

    for preferred_key in ("assay name", "sample name", "source name"):
        for key, value in row.items():
            if normalise_key(key) == preferred_key and value.strip():
                return value.strip()

    return ""


def get_preferred_value(row: dict[str, str], field_name: str) -> str:
    """Extract a preferred flattened metadata value from a row."""

    aliases = PREFERRED_FIELDS.get(field_name, ())
    keyed = {normalise_key(key): value.strip() for key, value in row.items()}

    for alias in aliases:
        value = keyed.get(normalise_key(alias), "")
        if value:
            return value

    return ""


def metadata_category(field_name: str) -> str:
    """Classify a metadata field by broad SDRF origin."""

    key = normalise_key(field_name)
    if key.startswith("characteristics["):
        return "characteristic"
    if key.startswith("factor value["):
        return "factor_value"
    if key.startswith("comment["):
        return "comment"
    if key.startswith("protocol"):
        return "protocol"
    return "field"


def iter_metadata_rows(job: MetadataJob) -> Iterator[tuple[dict[str, object], list[dict[str, object]]]]:
    """Yield wide and long records from one metadata TSV."""

    with open_text(job.metadata_tsv) as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            raw_header = next(reader)
        except StopIteration:
            return

        header = make_unique(raw_header)

        for row_index, raw_row in enumerate(reader, start=1):
            if not raw_row:
                continue
            padded = list(raw_row) + [""] * max(0, len(header) - len(raw_row))
            values = [value.strip() for value in padded[: len(header)]]
            row = dict(zip(header, values))
            sample_or_condition = choose_sample_or_condition(row=row)
            metadata_record_id = f"{job.experiment_accession}:{row_index}"

            wide = {
                "source_database": job.source_database,
                "experiment_accession": job.experiment_accession,
                "species_column": job.species_column,
                "sample_or_condition": sample_or_condition,
                "metadata_record_id": metadata_record_id,
                "organism": get_preferred_value(row, "organism"),
                "organism_part": get_preferred_value(row, "organism_part"),
                "developmental_stage": get_preferred_value(row, "developmental_stage"),
                "genotype": get_preferred_value(row, "genotype"),
                "cultivar": get_preferred_value(row, "cultivar"),
                "treatment": get_preferred_value(row, "treatment"),
                "condition": get_preferred_value(row, "condition"),
                "assay_name": get_preferred_value(row, "assay_name"),
                "source_name": get_preferred_value(row, "source_name"),
                "sample_name": get_preferred_value(row, "sample_name"),
                "source_file": str(job.metadata_tsv),
            }

            long_records: list[dict[str, object]] = []
            for field_name, value in row.items():
                value = value.strip()
                if value == "":
                    continue
                long_records.append(
                    {
                        "source_database": job.source_database,
                        "experiment_accession": job.experiment_accession,
                        "species_column": job.species_column,
                        "sample_or_condition": sample_or_condition,
                        "metadata_record_id": metadata_record_id,
                        "metadata_field": field_name,
                        "metadata_category": metadata_category(field_name),
                        "metadata_value": value,
                        "source_file": str(job.metadata_tsv),
                    }
                )

            yield wide, long_records


def wide_schema() -> pa.Schema:
    """Return the sample metadata wide schema."""

    return pa.schema(
        [
            pa.field("source_database", pa.string()),
            pa.field("experiment_accession", pa.string()),
            pa.field("species_column", pa.string()),
            pa.field("sample_or_condition", pa.string()),
            pa.field("metadata_record_id", pa.string()),
            pa.field("organism", pa.string()),
            pa.field("organism_part", pa.string()),
            pa.field("developmental_stage", pa.string()),
            pa.field("genotype", pa.string()),
            pa.field("cultivar", pa.string()),
            pa.field("treatment", pa.string()),
            pa.field("condition", pa.string()),
            pa.field("assay_name", pa.string()),
            pa.field("source_name", pa.string()),
            pa.field("sample_name", pa.string()),
            pa.field("source_file", pa.string()),
        ]
    )


def long_schema() -> pa.Schema:
    """Return the sample metadata long schema."""

    return pa.schema(
        [
            pa.field("source_database", pa.string()),
            pa.field("experiment_accession", pa.string()),
            pa.field("species_column", pa.string()),
            pa.field("sample_or_condition", pa.string()),
            pa.field("metadata_record_id", pa.string()),
            pa.field("metadata_field", pa.string()),
            pa.field("metadata_category", pa.string()),
            pa.field("metadata_value", pa.string()),
            pa.field("source_file", pa.string()),
        ]
    )


def rows_to_table(rows: list[dict[str, object]], schema: pa.Schema) -> pa.Table:
    """Convert dictionaries into an Arrow table."""

    columns = {name: [] for name in schema.names}
    for row in rows:
        for name in schema.names:
            columns[name].append(row.get(name, ""))
    arrays = [pa.array(columns[name], type=schema.field(name).type) for name in schema.names]
    return pa.Table.from_arrays(arrays, schema=schema)


def parquet_row_count(path: Path) -> int:
    """Return the number of rows in a Parquet file."""

    if not path.exists() or path.stat().st_size == 0:
        return 0
    try:
        return int(pq.ParquetFile(path).metadata.num_rows)
    except Exception:
        return 0


def write_partitioned_metadata(job: MetadataJob, output_dir: Path, force: bool) -> MetadataResult:
    """Import one metadata file into wide and long Parquet datasets."""

    if not job.metadata_tsv.exists() or job.metadata_tsv.stat().st_size == 0:
        return MetadataResult(job.metadata_tsv, job.experiment_accession, job.species_column, "skipped_missing_or_empty_input", False, 0, 0, 0, "metadata file missing or empty")

    wide_path = output_dir / "parquet" / "atlas_sample_metadata_wide" / f"species_column={job.species_column}" / f"experiment_accession={job.experiment_accession}" / "sample_metadata.parquet"
    long_path = output_dir / "parquet" / "atlas_sample_metadata_long" / f"species_column={job.species_column}" / f"experiment_accession={job.experiment_accession}" / "sample_metadata.parquet"

    if not force and parquet_row_count(wide_path) > 0 and parquet_row_count(long_path) > 0:
        return MetadataResult(job.metadata_tsv, job.experiment_accession, job.species_column, "skipped_existing_non_empty_parquet", True, parquet_row_count(wide_path), parquet_row_count(long_path), 0, "existing metadata Parquet contained rows")

    wide_path.parent.mkdir(parents=True, exist_ok=True)
    long_path.parent.mkdir(parents=True, exist_ok=True)
    wide_temp = make_closed_temp_path(
        parent_dir=wide_path.parent,
        suffix=".wide.parquet.partial",
    )
    long_temp = make_closed_temp_path(
        parent_dir=long_path.parent,
        suffix=".long.parquet.partial",
    )

    wide_writer: Optional[pq.ParquetWriter] = None
    long_writer: Optional[pq.ParquetWriter] = None
    metadata_records = 0
    long_rows = 0
    mapped_group_records = 0

    try:
        wide_writer = pq.ParquetWriter(wide_temp, wide_schema(), compression="snappy")
        long_writer = pq.ParquetWriter(long_temp, long_schema(), compression="snappy")
        wide_buffer: list[dict[str, object]] = []
        long_buffer: list[dict[str, object]] = []

        for wide, long_records in iter_metadata_rows(job=job):
            metadata_records += 1
            if str(wide.get("sample_or_condition", "")).strip():
                mapped_group_records += 1
            wide_buffer.append(wide)
            long_buffer.extend(long_records)

            if len(wide_buffer) >= 50000:
                wide_writer.write_table(rows_to_table(wide_buffer, wide_schema()))
                wide_buffer = []
            if len(long_buffer) >= 250000:
                long_writer.write_table(rows_to_table(long_buffer, long_schema()))
                long_rows += len(long_buffer)
                long_buffer = []

        if wide_buffer:
            wide_writer.write_table(rows_to_table(wide_buffer, wide_schema()))
        if long_buffer:
            long_writer.write_table(rows_to_table(long_buffer, long_schema()))
            long_rows += len(long_buffer)
    except Exception as error:  # noqa: BLE001
        for handle in (wide_writer, long_writer):
            if handle is not None:
                handle.close()
        for path in (wide_temp, long_temp):
            if path.exists():
                path.unlink()
        return MetadataResult(job.metadata_tsv, job.experiment_accession, job.species_column, "import_failed", False, metadata_records, long_rows, mapped_group_records, str(error))
    finally:
        if wide_writer is not None:
            wide_writer.close()
        if long_writer is not None:
            long_writer.close()

    wide_temp.replace(wide_path)
    long_temp.replace(long_path)
    wide_rows = parquet_row_count(wide_path)
    long_count = parquet_row_count(long_path)
    success = wide_rows > 0 and long_count > 0
    return MetadataResult(job.metadata_tsv, job.experiment_accession, job.species_column, "imported_to_parquet" if success else "imported_empty_parquet", success, wide_rows, long_count, mapped_group_records, "metadata imported" if success else "metadata Parquet had zero rows")


def read_downloaded_manifest(path: Path) -> list[dict[str, str]]:
    """Read the downloaded-files manifest."""

    with path.open(mode="r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def build_jobs(downloaded_files_tsv: Path) -> list[MetadataJob]:
    """Build metadata import jobs from the download manifest."""

    rows = read_downloaded_manifest(downloaded_files_tsv)
    jobs: list[MetadataJob] = []
    seen: set[tuple[str, str, str]] = set()

    for row in rows:
        if (row.get("file_type") or "").strip() not in METADATA_FILE_TYPES:
            continue
        if not parse_bool(row.get("success"), default=False):
            continue
        species_column = (row.get("species_column") or "").strip()
        experiment_accession = (row.get("experiment_accession") or "").strip()
        local_path = Path((row.get("local_path") or "").strip())
        source_database = (row.get("source_database") or "ExpressionAtlas").strip()
        if not species_column or not experiment_accession or not str(local_path):
            continue
        key = (species_column, experiment_accession, str(local_path))
        if key in seen:
            continue
        seen.add(key)
        jobs.append(MetadataJob(local_path, experiment_accession, species_column, source_database))

    return jobs


def write_summary(path: Path, results: list[MetadataResult]) -> None:
    """Write the metadata import summary."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "metadata_tsv",
        "experiment_accession",
        "species_column",
        "action",
        "success",
        "metadata_records",
        "long_rows",
        "mapped_group_records",
        "message",
    ]
    with path.open(mode="w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "metadata_tsv": str(result.metadata_tsv),
                    "experiment_accession": result.experiment_accession,
                    "species_column": result.species_column,
                    "action": result.action,
                    "success": "true" if result.success else "false",
                    "metadata_records": result.metadata_records,
                    "long_rows": result.long_rows,
                    "mapped_group_records": result.mapped_group_records,
                    "message": result.message,
                }
            )


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description="Import Expression Atlas sample metadata to Parquet.")
    parser.add_argument("--downloaded_files_tsv", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--force_import", default="false")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Run the sample metadata importer."""

    args = parse_args(argv)
    require_pyarrow()
    downloaded_files_tsv = Path(args.downloaded_files_tsv)
    output_dir = Path(args.output_dir)
    force = parse_bool(args.force_import, default=False)
    summary_path = output_dir / "manifests" / "atlas_sample_metadata_import_summary.tsv"

    if not downloaded_files_tsv.exists():
        raise SystemExit(f"Downloaded-files manifest does not exist: {downloaded_files_tsv}")

    jobs = build_jobs(downloaded_files_tsv=downloaded_files_tsv)
    print(f"Python sample metadata importer found {len(jobs)} metadata jobs", flush=True)
    results: list[MetadataResult] = []
    for index, job in enumerate(jobs, start=1):
        if index == 1 or index % 25 == 0 or index == len(jobs):
            print(f"Importing metadata {index}/{len(jobs)}: {job.species_column} {job.experiment_accession}", flush=True)
        results.append(write_partitioned_metadata(job=job, output_dir=output_dir, force=force))

    write_summary(summary_path, results)
    success = sum(1 for item in results if item.success)
    long_rows = sum(item.long_rows for item in results if item.success)
    print(f"Wrote sample metadata import summary: {summary_path}", flush=True)
    print(f"Successful metadata imports: {success}/{len(jobs)}", flush=True)
    print(f"Total metadata long rows: {long_rows}", flush=True)
    if len(jobs) > 0 and success == 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
