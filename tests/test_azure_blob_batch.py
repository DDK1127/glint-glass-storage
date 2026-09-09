from __future__ import annotations

import csv
import gzip
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from glass_sim.azure_blob_batch import (
    AzureBlobBatchConfig,
    extract_azure_blob_batch,
)
from glass_sim.azure_blob_preprocess import OUTPUT_COLUMNS


class AzureBlobBatchTests(unittest.TestCase):
    def test_extracts_consecutive_rows_and_rebases_arrival(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "canonical.csv.gz"
            reference = root / "lun.csv"
            self._write_canonical(source)
            self._write_reference(reference)
            config = AzureBlobBatchConfig(
                input_path=source,
                output_path=root / "batch.csv.gz",
                manifest_path=root / "batch.manifest.json",
                reference_lun_trace_path=reference,
                expected_source_sha256=hashlib.sha256(
                    source.read_bytes()
                ).hexdigest(),
                start_read_index=1,
                request_count=2,
            )

            manifest = extract_azure_blob_batch(config)
            with gzip.open(
                config.output_path,
                "rt",
                encoding="utf-8",
                newline="",
            ) as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual([row["TimestampMs"] for row in rows], ["2000", "3000"])
        self.assertEqual([row["ArrivalMs"] for row in rows], ["0", "1000"])
        self.assertEqual(manifest["batch"]["request_count"], 2)
        self.assertEqual(manifest["batch"]["unique_blob_versions"], 1)
        self.assertEqual(
            manifest["batch"]["repeated_blob_version_fraction"],
            0.5,
        )
        self.assertTrue(manifest["validation"]["passed"])

    @staticmethod
    def _write_canonical(path: Path) -> None:
        rows = [
            ["1000", "0", "1", "r", "u", "a", "i1", "b1", "e1", "type", "10"],
            ["2000", "1000", "2", "r", "u", "a", "i2", "b2", "e2", "type", "20"],
            ["3000", "2000", "3", "r", "u", "a", "i3", "b2", "e2", "type", "20"],
        ]
        with path.open("wb") as raw:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw,
                mtime=0,
            ) as compressed:
                with io.TextIOWrapper(
                    compressed,
                    encoding="utf-8",
                    newline="",
                ) as handle:
                    writer = csv.writer(handle, lineterminator="\n")
                    writer.writerow(OUTPUT_COLUMNS)
                    writer.writerows(rows)

    @staticmethod
    def _write_reference(path: Path) -> None:
        path.write_text(
            "\n".join(
                [
                    "Timestamp,Response,IOType,LUN,Offset,Size",
                    "1.0,0.1,R,0,10,4096",
                    "2.0,0.1,R,0,10,4096",
                ]
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
