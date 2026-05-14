#!/usr/bin/env python
"""Seed the `ruian_address` table from the ČÚZK RÚIAN OB_ADR export.

The geocode stage uses this table to resolve a source GPS coordinate to a
building (rooftop precision + the official RÚIAN address code). MVP scope is
Praha; ČÚZK keys the per-obec CSV files by obec code, so we read just one.

Usage (run inside the api container — see `make seed-ruian`):

    python scripts/seed_ruian.py --file /tmp/20260501_OB_ADR_csv.zip
    python scripts/seed_ruian.py --date 20260501
    python scripts/seed_ruian.py --url https://.../20260501_OB_ADR_csv.zip

With no source argument the URL is built from the first of the current month
(ČÚZK publishes a full-state extract monthly). The job is idempotent — rows
are upserted by `kod_adm`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.orm import RuianAddress as RuianAddressRow
from db.session import session_scope
from scraper.ruian import REGION_TO_OBEC_CODE, RuianAddress, read_ruian_csv
from shared.logging import configure_logging, get_logger

log = get_logger("scripts.seed_ruian")

CUZK_URL_TEMPLATE = "https://vdp.cuzk.cz/vymenny_format/csv/{date}_OB_ADR_csv.zip"

# Generous Czech Republic bounding box — used only as an axis-order guard so a
# projection mistake aborts the run loudly instead of poisoning the table.
_CZ_BBOX = (48.5, 51.1, 12.0, 18.9)  # min_lat, max_lat, min_lon, max_lon


def _build_url(date: str | None) -> str:
    if date is None:
        date = dt.date.today().replace(day=1).strftime("%Y%m%d")
    return CUZK_URL_TEMPLATE.format(date=date)


def _load_zip_bytes(args: argparse.Namespace) -> bytes:
    if args.file:
        path = Path(args.file)
        log.info("seed_ruian.read_file", path=str(path))
        return path.read_bytes()
    url = args.url or _build_url(args.date)
    log.info("seed_ruian.download", url=url)
    with httpx.Client(timeout=300.0, follow_redirects=True) as client:
        resp = client.get(url)
        if resp.status_code != 200:
            raise SystemExit(
                f"Download failed ({resp.status_code}) for {url}. "
                "ČÚZK publishes monthly — pass --date YYYYMMDD or --file."
            )
        return resp.content


def _extract_obec_csv(zip_bytes: bytes, obec_code: str) -> bytes:
    """Pull the single per-obec CSV out of the OB_ADR archive."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # ČÚZK names entries "<obec_code>_OB.csv", sometimes nested in a dir.
        wanted = f"{obec_code}_OB.csv"
        matches = [n for n in zf.namelist() if Path(n).name == wanted]
        if not matches:
            raise SystemExit(
                f"{wanted} not found in archive. Entries: {zf.namelist()[:5]}..."
            )
        return zf.read(matches[0])


def _sanity_check(addresses: list[RuianAddress]) -> None:
    """Abort if projected points don't land in Czechia (caught axis swap)."""
    min_lat, max_lat, min_lon, max_lon = _CZ_BBOX
    sample = addresses[:200]
    bad = [
        a
        for a in sample
        if not (min_lat <= a.lat <= max_lat and min_lon <= a.lon <= max_lon)
    ]
    if sample and len(bad) > len(sample) // 10:
        example = bad[0]
        raise SystemExit(
            f"Projection sanity check failed: {len(bad)}/{len(sample)} sampled "
            f"points fall outside Czechia (e.g. {example.kod_adm} → "
            f"{example.lat:.5f},{example.lon:.5f}). Check the S-JTSK transform."
        )


def _batches(it: Iterator[RuianAddress], size: int) -> Iterator[list[RuianAddress]]:
    batch: list[RuianAddress] = []
    for item in it:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _upsert(batch: list[RuianAddress]) -> None:
    rows = [
        {
            "kod_adm": a.kod_adm,
            "kod_obce": a.kod_obce,
            "nazev_obce": a.nazev_obce,
            "nazev_momc": a.nazev_momc,
            "nazev_casti_obce": a.nazev_casti_obce,
            "nazev_ulice": a.nazev_ulice,
            "cislo_domovni": a.cislo_domovni,
            "cislo_orientacni": a.cislo_orientacni,
            "psc": a.psc,
            "geom": f"SRID=4326;POINT({a.lon} {a.lat})",
        }
        for a in batch
    ]
    stmt = pg_insert(RuianAddressRow.__table__).values(rows)
    update_cols = {
        c.name: getattr(stmt.excluded, c.name)
        for c in RuianAddressRow.__table__.columns
        if c.name not in ("kod_adm", "updated_at")
    }
    update_cols["updated_at"] = func.now()
    stmt = stmt.on_conflict_do_update(index_elements=["kod_adm"], set_=update_cols)
    with session_scope() as db:
        db.execute(stmt)


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Seed ruian_address from ČÚZK OB_ADR.")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--file", help="Local OB_ADR zip file path.")
    src.add_argument("--url", help="Explicit OB_ADR zip URL.")
    parser.add_argument("--date", help="ČÚZK extract date YYYYMMDD (builds the URL).")
    parser.add_argument(
        "--region",
        default="praha",
        choices=sorted(REGION_TO_OBEC_CODE),
        help="Region to seed (MVP: praha only).",
    )
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()

    obec_code = REGION_TO_OBEC_CODE[args.region]
    zip_bytes = _load_zip_bytes(args)
    csv_bytes = _extract_obec_csv(zip_bytes, obec_code)

    # Materialise once: we need a sample for the sanity check, and the file
    # for a single obec is small enough to hold in memory.
    addresses = list(read_ruian_csv(csv_bytes))
    if not addresses:
        raise SystemExit("No usable RÚIAN addresses parsed — nothing to seed.")
    _sanity_check(addresses)

    total = 0
    for batch in _batches(iter(addresses), args.batch_size):
        _upsert(batch)
        total += len(batch)
        log.info("seed_ruian.progress", upserted=total)

    log.info(
        "seed_ruian.done",
        region=args.region,
        obec_code=obec_code,
        addresses=total,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
