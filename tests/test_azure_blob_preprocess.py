from __future__ import annotations

import bz2
import csv
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from glass_sim.azure_blob_preprocess import (
    AzureBlobPreprocessConfig,
    OUTPUT_COLUMNS,
    preprocess_azure_blob_trace,
)


HEADER = (
    "Timestamp,AnonRegion,AnonUserId,AnonAppName,"
    "AnonFunctionInvocationId,AnonBlobName,BlobType,AnonBlobETag,"
    "BlobBytes,Read,Write"
)


class AzureBlobPreprocessTests(unittest.TestCase):
    def test_preprocess_filters_reads_and_stably_sorts_without_deduplication(
        self,
    ) -> None:
        rows = [
            "3000,r,u,a,i1,blob-a,BlockBlob/type,etag-a,30.0,True,False",
            "1000,r,u,a,i2,blob-w,BlockBlob/type,etag-w,20.0,False,True",
            "2000,r,u,a,i3,blob-b,BlockBlob/type,etag-b,10.0,True,False",
            "2000,r,u,a,i4,blob-b,BlockBlob/type,etag-b,10.0,True,False",
            "4000,r,u,a,i5,blob-n,BlockBlob/type,etag-n,0.0,False,False",
            "2500,r,u,a,i6,blob-m,BlockBlob/type,etag-m,,True,False",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv.bz2"
            with bz2.open(source, "wt", encoding="utf-8", newline="") as handle:
                handle.write(HEADER + "\n")
                handle.write("\n".join(rows) + "\n")
            config = self._config(root, source)

            manifest = preprocess_azure_blob_trace(config)
            output = self._read_gzip_csv(config.output_path)
            sample = self._read_gzip_csv(config.sample_output_path)
            first_output_sha256 = manifest["output"]["sha256"]
            second_manifest = preprocess_azure_blob_trace(config)

        self.assertEqual(tuple(output[0]), OUTPUT_COLUMNS)
        self.assertEqual([row[0] for row in output[1:]], ["2000", "2000", "3000"])
        self.assertEqual([row[2] for row in output[1:]], ["3", "4", "1"])
        self.assertEqual([row[1] for row in output[1:]], ["0", "0", "1000"])
        self.assertEqual([row[7] for row in output[1:]], ["blob-b", "blob-b", "blob-a"])
        self.assertEqual(len(sample) - 1, 2)
        self.assertEqual(manifest["source_stats"]["input_rows"], 6)
        self.assertEqual(manifest["source_stats"]["read_rows"], 4)
        self.assertEqual(manifest["source_stats"]["eligible_read_rows"], 3)
        self.assertEqual(
            manifest["source_stats"]["excluded_read_rows_missing_blob_bytes"],
            1,
        )
        self.assertEqual(manifest["source_stats"]["non_read_rows"], 2)
        self.assertEqual(manifest["source_stats"]["source_order_timestamp_descents"], 2)
        self.assertTrue(manifest["validation"]["passed"])
        self.assertEqual(
            first_output_sha256,
            second_manifest["output"]["sha256"],
        )

    def test_preprocess_rejects_source_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.csv.bz2"
            with bz2.open(source, "wt", encoding="utf-8") as handle:
                handle.write(HEADER + "\n")
            config = self._config(root, source, expected_sha256="0" * 64)

            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                preprocess_azure_blob_trace(config)

    @staticmethod
    def _config(
        root: Path,
        source: Path,
        expected_sha256: str | None = None,
    ) -> AzureBlobPreprocessConfig:
        checksum = hashlib.sha256(source.read_bytes()).hexdigest()
        return AzureBlobPreprocessConfig(
            input_path=source,
            output_path=root / "processed" / "full.csv.gz",
            sample_output_path=root / "processed" / "sample.csv.gz",
            manifest_path=root / "processed" / "manifest.json",
            temp_dir=root / "tmp",
            expected_source_sha256=expected_sha256 or checksum,
            sample_read_requests=2,
            sort_buffer="1M",
            max_input_rows=None,
        )

    @staticmethod
    def _read_gzip_csv(path: Path) -> list[list[str]]:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            return list(csv.reader(handle))


if __name__ == "__main__":
    unittest.main()
