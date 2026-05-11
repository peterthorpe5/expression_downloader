#!/usr/bin/env python3
"""Download Expression Atlas files from an existing FTP manifest.

This script is intentionally dependency-light and uses only the Python standard
library. It reads the TSV manifest produced by the R package, checks whether
remote files exist and are non-empty, skips local files that already exist and
are non-empty, and writes TSV manifests compatible with the R import scripts.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional


@dataclass
class RemoteStatus:
    """Container for remote file status information."""

    remote_exists: bool
    remote_non_empty: bool
    status_code: Optional[int]
    remote_bytes: Optional[int]
    check_method: str


@dataclass
class DownloadStatus:
    """Container for local download status information."""

    action: str
    success: bool
    local_bytes: Optional[int]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed command-line arguments.
    """

    parser = argparse.ArgumentParser(
        description="Check and download Expression Atlas files from a TSV manifest."
    )
    parser.add_argument(
        "--ftp_manifest_tsv",
        required=True,
        help="Input FTP manifest TSV produced by 03a_build_ftp_manifest.R.",
    )
    parser.add_argument(
        "--checked_manifest_tsv",
        required=True,
        help="Output TSV containing remote file checks.",
    )
    parser.add_argument(
        "--download_log_tsv",
        required=True,
        help="Output TSV containing download actions.",
    )
    parser.add_argument(
        "--downloaded_files_tsv",
        required=True,
        help="Output TSV listing successfully available local files.",
    )
    parser.add_argument(
        "--force_download",
        choices=["true", "false"],
        default="false",
        help="Whether to redownload non-empty local files.",
    )
    parser.add_argument(
        "--timeout_seconds",
        type=int,
        default=30,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Number of download retries after the first attempt.",
    )
    parser.add_argument(
        "--sleep_seconds",
        type=float,
        default=0.5,
        help="Sleep time between repeated requests.",
    )
    return parser.parse_args()


def local_file_is_usable(*, file_path: str, minimum_bytes: int = 1) -> bool:
    """Check whether a local file exists and is non-empty.

    Args:
        file_path: Path to a local file.
        minimum_bytes: Minimum acceptable file size in bytes.

    Returns:
        True when the file exists and has at least ``minimum_bytes`` bytes.
    """

    path = Path(file_path)
    return path.is_file() and path.stat().st_size >= minimum_bytes


def read_tsv(*, tsv_path: str) -> List[Dict[str, str]]:
    """Read a tab-separated file into a list of dictionaries.

    Args:
        tsv_path: Path to the input TSV file.

    Returns:
        Rows from the TSV file.
    """

    with open(file=tsv_path, mode="r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(f=handle, delimiter="\t")
        return list(reader)


def write_tsv(*, rows: Iterable[Dict[str, object]], tsv_path: str, fieldnames: List[str]) -> None:
    """Write rows to a tab-separated file.

    Args:
        rows: Iterable of dictionary rows.
        tsv_path: Output TSV path.
        fieldnames: Ordered output field names.
    """

    output_path = Path(tsv_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file=output_path, mode="w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            f=handle,
            fieldnames=fieldnames,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(rowdict=row)


def make_request(*, url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None) -> urllib.request.Request:
    """Create a urllib request.

    Args:
        url: Remote URL.
        method: HTTP method.
        headers: Optional request headers.

    Returns:
        Configured urllib request.
    """

    return urllib.request.Request(url=url, method=method, headers=headers or {})


def check_remote_file(*, url: str, timeout_seconds: int = 30) -> RemoteStatus:
    """Check whether a remote file exists and is non-empty.

    Args:
        url: Remote URL.
        timeout_seconds: HTTP timeout in seconds.

    Returns:
        Remote status details.
    """

    try:
        request = make_request(url=url, method="HEAD")
        with urllib.request.urlopen(url=request, timeout=timeout_seconds) as response:
            status_code = int(response.status)
            content_length = response.headers.get("Content-Length")
            remote_bytes = int(content_length) if content_length else None
            remote_exists = status_code < 400
            remote_non_empty = remote_exists and remote_bytes is not None and remote_bytes > 0
            if remote_non_empty:
                return RemoteStatus(
                    remote_exists=True,
                    remote_non_empty=True,
                    status_code=status_code,
                    remote_bytes=remote_bytes,
                    check_method="HEAD",
                )
            if status_code >= 400:
                return RemoteStatus(
                    remote_exists=False,
                    remote_non_empty=False,
                    status_code=status_code,
                    remote_bytes=remote_bytes,
                    check_method="HEAD",
                )
    except urllib.error.HTTPError as error:
        return RemoteStatus(
            remote_exists=False,
            remote_non_empty=False,
            status_code=int(error.code),
            remote_bytes=None,
            check_method="HEAD_HTTP_ERROR",
        )
    except Exception:
        pass

    try:
        request = make_request(url=url, method="GET", headers={"Range": "bytes=0-0"})
        with urllib.request.urlopen(url=request, timeout=timeout_seconds) as response:
            body = response.read(1)
            status_code = int(response.status)
            return RemoteStatus(
                remote_exists=status_code < 400,
                remote_non_empty=status_code < 400 and len(body) > 0,
                status_code=status_code,
                remote_bytes=None,
                check_method="GET_RANGE",
            )
    except urllib.error.HTTPError as error:
        return RemoteStatus(
            remote_exists=False,
            remote_non_empty=False,
            status_code=int(error.code),
            remote_bytes=None,
            check_method="GET_RANGE_HTTP_ERROR",
        )
    except Exception:
        return RemoteStatus(
            remote_exists=False,
            remote_non_empty=False,
            status_code=None,
            remote_bytes=None,
            check_method="GET_RANGE_FAILED",
        )


def download_url(*, url: str, local_path: str, timeout_seconds: int = 30) -> bool:
    """Download a URL to a local path via a temporary partial file.

    Args:
        url: Remote URL.
        local_path: Local output path.
        timeout_seconds: HTTP timeout in seconds.

    Returns:
        True when the file was downloaded and is non-empty.
    """

    output_path = Path(local_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="wb",
        delete=False,
        dir=str(output_path.parent),
        suffix=".partial",
    ) as temporary_handle:
        temporary_path = Path(temporary_handle.name)

    try:
        request = make_request(url=url, method="GET")
        with urllib.request.urlopen(url=request, timeout=timeout_seconds) as response:
            with open(file=temporary_path, mode="wb") as output_handle:
                shutil.copyfileobj(fsrc=response, fdst=output_handle)

        if not local_file_is_usable(file_path=str(temporary_path)):
            temporary_path.unlink(missing_ok=True)
            return False

        temporary_path.replace(output_path)
        return True
    except Exception:
        temporary_path.unlink(missing_ok=True)
        return False


def download_if_needed(
    *,
    url: str,
    local_path: str,
    remote_status: RemoteStatus,
    force_download: bool = False,
    retries: int = 2,
    timeout_seconds: int = 30,
    sleep_seconds: float = 0.5,
) -> DownloadStatus:
    """Download a remote file only when required.

    Args:
        url: Remote URL.
        local_path: Local output path.
        remote_status: Precomputed remote status.
        force_download: Whether to replace a usable local file.
        retries: Number of retries after the first attempt.
        timeout_seconds: HTTP timeout in seconds.
        sleep_seconds: Delay between attempts.

    Returns:
        Download status details.
    """

    if local_file_is_usable(file_path=local_path) and not force_download:
        return DownloadStatus(
            action="skipped_existing_local_file",
            success=True,
            local_bytes=Path(local_path).stat().st_size,
        )

    if not remote_status.remote_exists or not remote_status.remote_non_empty:
        return DownloadStatus(
            action="skipped_remote_missing_or_empty",
            success=False,
            local_bytes=None,
        )

    for attempt_number in range(retries + 1):
        if attempt_number > 0:
            time.sleep(sleep_seconds)

        success = download_url(
            url=url,
            local_path=local_path,
            timeout_seconds=timeout_seconds,
        )
        if success:
            return DownloadStatus(
                action="downloaded",
                success=True,
                local_bytes=Path(local_path).stat().st_size,
            )

    return DownloadStatus(action="download_failed", success=False, local_bytes=None)


def main() -> int:
    """Run the Expression Atlas downloader.

    Returns:
        Exit status code.
    """

    args = parse_args()
    force_download = args.force_download.lower() == "true"

    manifest_rows = read_tsv(tsv_path=args.ftp_manifest_tsv)
    checked_rows: List[Dict[str, object]] = []
    download_rows: List[Dict[str, object]] = []
    downloaded_rows: List[Dict[str, object]] = []

    for index, row in enumerate(manifest_rows, start=1):
        url = row["url"]
        local_path = row["local_path"]
        print(f"[{index}/{len(manifest_rows)}] Checking {url}", file=sys.stderr)

        remote_status = check_remote_file(url=url, timeout_seconds=args.timeout_seconds)
        checked_row: Dict[str, object] = dict(row)
        checked_row.update(
            {
                "remote_exists": remote_status.remote_exists,
                "remote_non_empty": remote_status.remote_non_empty,
                "status_code": "" if remote_status.status_code is None else remote_status.status_code,
                "remote_bytes": "" if remote_status.remote_bytes is None else remote_status.remote_bytes,
                "check_method": remote_status.check_method,
            }
        )
        checked_rows.append(checked_row)

        download_status = download_if_needed(
            url=url,
            local_path=local_path,
            remote_status=remote_status,
            force_download=force_download,
            retries=args.retries,
            timeout_seconds=args.timeout_seconds,
            sleep_seconds=args.sleep_seconds,
        )
        download_row: Dict[str, object] = {
            "url": url,
            "local_path": local_path,
            "action": download_status.action,
            "success": download_status.success,
            "local_bytes": "" if download_status.local_bytes is None else download_status.local_bytes,
        }
        download_rows.append(download_row)

        if download_status.success:
            downloaded_row: Dict[str, object] = dict(row)
            downloaded_row["local_bytes"] = download_status.local_bytes
            downloaded_rows.append(downloaded_row)

    checked_fields = list(manifest_rows[0].keys()) + [
        "remote_exists",
        "remote_non_empty",
        "status_code",
        "remote_bytes",
        "check_method",
    ] if manifest_rows else [
        "experiment_accession",
        "species_column",
        "file_type",
        "file_name",
        "url",
        "local_path",
        "remote_exists",
        "remote_non_empty",
        "status_code",
        "remote_bytes",
        "check_method",
    ]

    downloaded_fields = list(manifest_rows[0].keys()) + ["local_bytes"] if manifest_rows else [
        "experiment_accession",
        "species_column",
        "file_type",
        "file_name",
        "url",
        "local_path",
        "local_bytes",
    ]

    write_tsv(rows=checked_rows, tsv_path=args.checked_manifest_tsv, fieldnames=checked_fields)
    write_tsv(
        rows=download_rows,
        tsv_path=args.download_log_tsv,
        fieldnames=["url", "local_path", "action", "success", "local_bytes"],
    )
    write_tsv(rows=downloaded_rows, tsv_path=args.downloaded_files_tsv, fieldnames=downloaded_fields)

    print(f"Wrote checked manifest: {args.checked_manifest_tsv}", file=sys.stderr)
    print(f"Wrote download log: {args.download_log_tsv}", file=sys.stderr)
    print(f"Wrote downloaded files: {args.downloaded_files_tsv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
