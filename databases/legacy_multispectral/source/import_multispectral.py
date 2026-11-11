#!/usr/bin/env python3
"""Scan lettuce multispectral folders and generate idempotent MySQL import SQL."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


EXPECTED_BANDS = (
    "L405", "L430", "L450", "L475", "L500", "L540", "L600", "L630",
    "L680", "L700", "L730", "L770", "L800", "L850", "L900", "L980",
)
ALLOWED_GROUP_COUNTS = (2, 3, 4, 6, 12)
EXPLICIT_FOLDER_RE = re.compile(
    r"^(?P<mmdd>\d{4})_lettuce_(?P<round>\d+)_(?P<rack>[ABCD])$",
    re.IGNORECASE,
)
COMPACT_FOLDER_RE = re.compile(
    r"^(?P<mmdd>\d{4})_lettuce_(?P<round>\d+)(?P<rack>[ABCD])$",
    re.IGNORECASE,
)
IMAGE_RE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})__(?P<kind>[^.]+)\.png$",
    re.IGNORECASE,
)


@dataclass
class CaptureRecord:
    key: str
    captured_at: datetime
    spectral: dict[str, Path] = field(default_factory=dict)
    auxiliary: dict[str, Path] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    sequence: int = 0
    light_code: str | None = None
    group_no: int | None = None
    plant_positions: tuple[int, ...] = ()
    mapping_status: str = "UNMAPPED"


@dataclass
class FolderRecord:
    path: Path
    folder_mmdd: str
    acquisition_no: int
    rack_code: str
    captures: list[CaptureRecord]
    issues: list[str] = field(default_factory=list)
    batch_code: str = ""
    mapping_status: str = "NEEDS_REVIEW"
    level_group_counts: tuple[int, int, int] | None = None

    @property
    def capture_date(self) -> date:
        return self.captures[0].captured_at.date()


def normalized_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def hash_text(value: str) -> str:
    return hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()


def sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def sql_nullable_string(value: str | None) -> str:
    return "NULL" if value is None else sql_string(value)


def parse_folder_descriptor(
    folder_name: str, sibling_names: set[str]
) -> tuple[str, int, str] | None:
    explicit = EXPLICIT_FOLDER_RE.fullmatch(folder_name)
    if explicit:
        return (
            explicit.group("mmdd"),
            int(explicit.group("round")),
            explicit.group("rack").upper(),
        )

    compact = COMPACT_FOLDER_RE.fullmatch(folder_name)
    if not compact:
        return None

    mmdd = compact.group("mmdd")
    acquisition_no = int(compact.group("round"))
    rack_code = compact.group("rack").upper()

    # "..._3D" can mean rack D for acquisition 3 or a 3D data folder.
    # Accept compact D only when matching A/B/C siblings prove it is rack D.
    if rack_code == "D":
        sibling_prefix = f"{mmdd}_lettuce_{acquisition_no}"
        has_2d_sibling = any(
            candidate in sibling_names
            for suffix in ("A", "B", "C", "_A", "_B", "_C")
            for candidate in (sibling_prefix + suffix,)
        )
        if not has_2d_sibling:
            return None

    return mmdd, acquisition_no, rack_code


def scan_capture_files(folder: Path) -> tuple[list[CaptureRecord], list[str]]:
    captures_by_key: dict[str, CaptureRecord] = {}
    folder_issues: list[str] = []

    for image_path in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
        if not image_path.is_file():
            continue
        match = IMAGE_RE.fullmatch(image_path.name)
        if not match:
            continue

        key = match.group("stamp")
        token = match.group("kind").upper()
        if token == "COMPLETE":
            continue

        captured_at = datetime.strptime(key, "%Y-%m-%d_%H-%M-%S")
        capture = captures_by_key.setdefault(
            key, CaptureRecord(key=key, captured_at=captured_at)
        )

        if token in EXPECTED_BANDS:
            if token in capture.spectral:
                capture.issues.append(f"duplicate band {token}")
            capture.spectral[token] = image_path
            continue

        product_code = {"COLOR": "COLOR", "LNDVI": "NDVI", "LNDRE": "NDRE"}.get(token)
        if product_code:
            if product_code in capture.auxiliary:
                capture.issues.append(f"duplicate product {product_code}")
            capture.auxiliary[product_code] = image_path

    captures = sorted(captures_by_key.values(), key=lambda item: item.captured_at)
    captures = [capture for capture in captures if capture.spectral]
    for sequence, capture in enumerate(captures, start=1):
        capture.sequence = sequence
        missing = sorted(set(EXPECTED_BANDS) - set(capture.spectral))
        unexpected = sorted(set(capture.spectral) - set(EXPECTED_BANDS))
        if missing:
            capture.issues.append("missing bands: " + ",".join(missing))
        if unexpected:
            capture.issues.append("unexpected bands: " + ",".join(unexpected))

    if not captures:
        folder_issues.append("no multispectral capture sets found")

    return captures, folder_issues


def scan_root(root: Path) -> list[FolderRecord]:
    sibling_names = {item.name for item in root.iterdir() if item.is_dir()}
    records: list[FolderRecord] = []

    for folder in sorted(
        (item for item in root.iterdir() if item.is_dir()),
        key=lambda item: item.name.casefold(),
    ):
        descriptor = parse_folder_descriptor(folder.name, sibling_names)
        if descriptor is None:
            continue
        mmdd, acquisition_no, rack_code = descriptor
        captures, issues = scan_capture_files(folder)
        if not captures:
            continue
        record = FolderRecord(
            path=folder,
            folder_mmdd=mmdd,
            acquisition_no=acquisition_no,
            rack_code=rack_code,
            captures=captures,
            issues=issues,
        )
        if record.capture_date.strftime("%m%d") != mmdd:
            record.issues.append(
                f"folder date {mmdd} differs from image date "
                f"{record.capture_date.strftime('%m%d')}"
            )
        records.append(record)

    assign_batches(records)
    return records


def assign_batches(records: list[FolderRecord]) -> None:
    timepoints = sorted(
        {(record.capture_date, record.acquisition_no) for record in records}
    )
    batch_for_timepoint: dict[tuple[date, int], str] = {}
    previous_round: int | None = None
    current_batch = ""

    for capture_date, acquisition_no in timepoints:
        if previous_round is None or acquisition_no <= previous_round:
            current_batch = f"batch-{capture_date.strftime('%Y%m%d')}"
        batch_for_timepoint[(capture_date, acquisition_no)] = current_batch
        previous_round = acquisition_no

    for record in records:
        record.batch_code = batch_for_timepoint[
            (record.capture_date, record.acquisition_no)
        ]


def load_mapping_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"folder_mappings": {}, "exclude_timestamps": {}}
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    config.setdefault("folder_mappings", {})
    config.setdefault("exclude_timestamps", {})
    return config


def capture_is_excluded(capture: CaptureRecord, excluded_values: set[str]) -> bool:
    aliases = {
        capture.key,
        capture.captured_at.strftime("%Y-%m-%d %H:%M:%S"),
        capture.captured_at.isoformat(),
    }
    return bool(aliases & excluded_values)


def valid_group_counts(counts: tuple[int, int, int], capture_count: int) -> bool:
    return (
        sum(counts) == capture_count
        and all(count in ALLOWED_GROUP_COUNTS for count in counts)
        and all(12 % count == 0 for count in counts)
    )


def apply_mapping(record: FolderRecord, config: dict[str, Any]) -> None:
    folder_name = record.path.name
    excluded_values = {
        str(value)
        for value in config["exclude_timestamps"].get(folder_name, [])
    }
    usable: list[CaptureRecord] = []

    for capture in record.captures:
        if capture_is_excluded(capture, excluded_values):
            capture.mapping_status = "EXCLUDED"
        else:
            usable.append(capture)

    configured_counts = config["folder_mappings"].get(folder_name)
    mapping_mode = "OVERRIDE" if configured_counts is not None else "AUTO"
    counts: tuple[int, int, int] | None = None

    if configured_counts is not None:
        try:
            candidate = tuple(int(value) for value in configured_counts)
        except (TypeError, ValueError):
            candidate = ()
        if len(candidate) == 3 and valid_group_counts(candidate, len(usable)):
            counts = candidate
        else:
            record.issues.append(
                "invalid folder mapping; expected three valid group counts "
                f"summing to {len(usable)}"
            )
    elif len(usable) % 3 == 0:
        equal_count = len(usable) // 3
        candidate = (equal_count, equal_count, equal_count)
        if valid_group_counts(candidate, len(usable)):
            counts = candidate

    if counts is None:
        record.mapping_status = "NEEDS_REVIEW"
        record.issues.append(
            f"cannot uniquely split {len(usable)} capture sets across three lights"
        )
        return

    record.level_group_counts = counts
    record.mapping_status = mapping_mode
    offset = 0
    for level_no, group_count in enumerate(counts, start=1):
        plants_per_image = 12 // group_count
        for index, capture in enumerate(
            usable[offset : offset + group_count], start=1
        ):
            first_position = (index - 1) * plants_per_image + 1
            last_position = index * plants_per_image
            capture.light_code = f"{record.rack_code}-{level_no}"
            capture.group_no = index
            capture.plant_positions = tuple(
                range(first_position, last_position + 1)
            )
            capture.mapping_status = mapping_mode
        offset += group_count

    if record.issues or any(capture.issues for capture in record.captures):
        record.mapping_status = "NEEDS_REVIEW"


def candidate_splits(capture_count: int) -> list[tuple[int, int, int]]:
    return [
        values
        for values in itertools.product(ALLOWED_GROUP_COUNTS, repeat=3)
        if sum(values) == capture_count
    ]


def write_report(records: list[FolderRecord], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "folder", "batch", "capture_date", "acquisition_no", "rack",
                "capture_sets", "mapping_status", "level_1_groups",
                "level_2_groups", "level_3_groups", "candidate_splits", "issues",
            ),
        )
        writer.writeheader()
        for record in records:
            counts = record.level_group_counts or ("", "", "")
            candidates = candidate_splits(
                sum(c.mapping_status != "EXCLUDED" for c in record.captures)
            )
            issues = record.issues + [
                f"{capture.key}: {issue}"
                for capture in record.captures
                for issue in capture.issues
            ]
            writer.writerow(
                {
                    "folder": record.path.name,
                    "batch": record.batch_code,
                    "capture_date": record.capture_date.isoformat(),
                    "acquisition_no": record.acquisition_no,
                    "rack": record.rack_code,
                    "capture_sets": len(record.captures),
                    "mapping_status": record.mapping_status,
                    "level_1_groups": counts[0],
                    "level_2_groups": counts[1],
                    "level_3_groups": counts[2],
                    "candidate_splits": ";".join(
                        "/".join(str(value) for value in candidate)
                        for candidate in candidates
                    ),
                    "issues": " | ".join(issues),
                }
            )


def write_review_config(records: list[FolderRecord], config_path: Path) -> None:
    review = {
        "folder_mappings": {
            record.path.name: None
            for record in records
            if record.mapping_status == "NEEDS_REVIEW"
        },
        "exclude_timestamps": {},
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(review, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def file_sql_values(path: Path) -> tuple[str, str, int, str]:
    path_text = normalized_path(path)
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return path_text, hash_text(path_text), stat.st_size, modified


def capture_id_sql(folder_hash: str, captured_at: datetime) -> str:
    timestamp = captured_at.strftime("%Y-%m-%d %H:%M:%S")
    return (
        "(SELECT cg.id FROM capture_groups AS cg "
        "JOIN source_folders AS sf ON sf.id = cg.source_folder_id "
        f"WHERE sf.source_path_hash = UNHEX('{folder_hash}') "
        f"AND cg.captured_at = '{timestamp}')"
    )


def generate_import_sql(records: list[FolderRecord], output_path: Path) -> None:
    lines = [
        "USE lettuce_multispectral;",
        "SET NAMES utf8mb4;",
        "START TRANSACTION;",
        "",
    ]

    batches: dict[str, list[FolderRecord]] = {}
    for record in records:
        batches.setdefault(record.batch_code, []).append(record)

    for batch_code, batch_records in sorted(batches.items()):
        started_on = min(record.capture_date for record in batch_records).isoformat()
        ended_on = max(record.capture_date for record in batch_records).isoformat()
        lines.extend(
            [
                "INSERT INTO crop_batches (batch_code, started_on, ended_on)",
                f"VALUES ({sql_string(batch_code)}, '{started_on}', '{ended_on}')",
                "ON DUPLICATE KEY UPDATE",
                "  started_on = VALUES(started_on), ended_on = VALUES(ended_on);",
                "",
                "INSERT INTO plants (batch_id, light_condition_id, position_no)",
                "SELECT cb.id, lc.id, positions.position_no",
                "FROM crop_batches AS cb",
                "CROSS JOIN light_conditions AS lc",
                "CROSS JOIN (",
                "  SELECT 1 AS position_no UNION ALL SELECT 2 UNION ALL SELECT 3",
                "  UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6",
                "  UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9",
                "  UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12",
                ") AS positions",
                f"WHERE cb.batch_code = {sql_string(batch_code)}",
                "ON DUPLICATE KEY UPDATE position_no = VALUES(position_no);",
                "",
            ]
        )

    for record in records:
        folder_path = normalized_path(record.path)
        folder_hash = hash_text(folder_path)
        lines.extend(
            [
                "INSERT INTO source_folders (",
                "  batch_id, folder_name, folder_path, source_path_hash, capture_date,",
                "  acquisition_no, rack_code, capture_set_count, mapping_status, imported_at",
                ") VALUES (",
                f"  (SELECT id FROM crop_batches WHERE batch_code = {sql_string(record.batch_code)}),",
                f"  {sql_string(record.path.name)}, {sql_string(folder_path)}, UNHEX('{folder_hash}'),",
                f"  '{record.capture_date.isoformat()}', {record.acquisition_no},",
                f"  '{record.rack_code}', {len(record.captures)}, '{record.mapping_status}', NOW()",
                ") ON DUPLICATE KEY UPDATE",
                "  batch_id = VALUES(batch_id), folder_name = VALUES(folder_name),",
                "  capture_date = VALUES(capture_date), acquisition_no = VALUES(acquisition_no),",
                "  rack_code = VALUES(rack_code), capture_set_count = VALUES(capture_set_count),",
                "  mapping_status = VALUES(mapping_status), imported_at = NOW();",
                "",
            ]
        )

        for capture in record.captures:
            captured_at = capture.captured_at.strftime("%Y-%m-%d %H:%M:%S")
            light_id = (
                "NULL"
                if capture.light_code is None
                else f"(SELECT id FROM light_conditions WHERE code = '{capture.light_code}')"
            )
            first_position = (
                str(capture.plant_positions[0]) if capture.plant_positions else "NULL"
            )
            last_position = (
                str(capture.plant_positions[-1]) if capture.plant_positions else "NULL"
            )
            plants_per_image = (
                str(len(capture.plant_positions)) if capture.plant_positions else "NULL"
            )
            group_no = str(capture.group_no) if capture.group_no else "NULL"
            lines.extend(
                [
                    "INSERT INTO capture_groups (",
                    "  source_folder_id, light_condition_id, captured_at, source_timestamp,",
                    "  sequence_in_folder, group_no, plants_per_image,",
                    "  first_plant_position, last_plant_position, mapping_status",
                    ") VALUES (",
                    "  (SELECT id FROM source_folders "
                    f"WHERE source_path_hash = UNHEX('{folder_hash}')),",
                    f"  {light_id}, '{captured_at}', {sql_string(capture.key)},",
                    f"  {capture.sequence}, {group_no}, {plants_per_image},",
                    f"  {first_position}, {last_position}, '{capture.mapping_status}'",
                    ") ON DUPLICATE KEY UPDATE",
                    "  light_condition_id = VALUES(light_condition_id),",
                    "  source_timestamp = VALUES(source_timestamp),",
                    "  sequence_in_folder = VALUES(sequence_in_folder),",
                    "  group_no = VALUES(group_no), plants_per_image = VALUES(plants_per_image),",
                    "  first_plant_position = VALUES(first_plant_position),",
                    "  last_plant_position = VALUES(last_plant_position),",
                    "  mapping_status = VALUES(mapping_status);",
                ]
            )

            group_id = capture_id_sql(folder_hash, capture.captured_at)
            for band_code in EXPECTED_BANDS:
                image_path = capture.spectral.get(band_code)
                if image_path is None:
                    continue
                path_text, path_hash, size, modified = file_sql_values(image_path)
                lines.extend(
                    [
                        "INSERT INTO multispectral_images (",
                        "  capture_group_id, band_id, file_name, file_path, file_path_hash,",
                        "  file_size_bytes, file_modified_at",
                        ") VALUES (",
                        f"  {group_id},",
                        f"  (SELECT id FROM spectral_bands WHERE code = '{band_code}'),",
                        f"  {sql_string(image_path.name)}, {sql_string(path_text)},",
                        f"  UNHEX('{path_hash}'), {size}, '{modified}'",
                        ") ON DUPLICATE KEY UPDATE",
                        "  file_name = VALUES(file_name), file_path = VALUES(file_path),",
                        "  file_path_hash = VALUES(file_path_hash),",
                        "  file_size_bytes = VALUES(file_size_bytes),",
                        "  file_modified_at = VALUES(file_modified_at);",
                    ]
                )

            for product_code, image_path in sorted(capture.auxiliary.items()):
                path_text, path_hash, size, modified = file_sql_values(image_path)
                lines.extend(
                    [
                        "INSERT INTO auxiliary_images (",
                        "  capture_group_id, product_code, file_name, file_path,",
                        "  file_path_hash, file_size_bytes, file_modified_at",
                        ") VALUES (",
                        f"  {group_id}, '{product_code}', {sql_string(image_path.name)},",
                        f"  {sql_string(path_text)}, UNHEX('{path_hash}'), {size}, '{modified}'",
                        ") ON DUPLICATE KEY UPDATE",
                        "  file_name = VALUES(file_name), file_path = VALUES(file_path),",
                        "  file_path_hash = VALUES(file_path_hash),",
                        "  file_size_bytes = VALUES(file_size_bytes),",
                        "  file_modified_at = VALUES(file_modified_at);",
                    ]
                )

            lines.append(
                f"DELETE FROM capture_group_plants WHERE capture_group_id = {group_id};"
            )
            if capture.light_code and capture.plant_positions:
                for slot_no, position_no in enumerate(capture.plant_positions, start=1):
                    lines.extend(
                        [
                            "INSERT INTO capture_group_plants (capture_group_id, plant_id, slot_no)",
                            f"SELECT {group_id}, p.id, {slot_no}",
                            "FROM plants AS p",
                            "JOIN crop_batches AS cb ON cb.id = p.batch_id",
                            "JOIN light_conditions AS lc ON lc.id = p.light_condition_id",
                            f"WHERE cb.batch_code = {sql_string(record.batch_code)}",
                            f"  AND lc.code = '{capture.light_code}'",
                            f"  AND p.position_no = {position_no};",
                        ]
                    )
            lines.append("")

    lines.extend(["COMMIT;", ""])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def print_summary(records: list[FolderRecord]) -> None:
    statuses: dict[str, int] = {}
    for record in records:
        statuses[record.mapping_status] = statuses.get(record.mapping_status, 0) + 1
    capture_count = sum(len(record.captures) for record in records)
    image_count = sum(
        len(capture.spectral)
        for record in records
        for capture in record.captures
    )
    print(f"Folders: {len(records)}")
    print(f"Capture sets: {capture_count}")
    print(f"Spectral images: {image_count}")
    for status, count in sorted(statuses.items()):
        print(f"{status}: {count}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--write-review-config", type=Path)
    parser.add_argument("--sql-output", type=Path)
    args = parser.parse_args()

    if not args.root.is_dir():
        parser.error(f"root directory does not exist: {args.root}")

    config = load_mapping_config(args.config)
    records = scan_root(args.root)
    for record in records:
        apply_mapping(record, config)

    if args.report:
        write_report(records, args.report)
    if args.write_review_config:
        write_review_config(records, args.write_review_config)
    if args.sql_output:
        generate_import_sql(records, args.sql_output)

    print_summary(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
