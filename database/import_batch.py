"""Load a validated snapshot into an initialized MySQL instance, as loading.

Credentials are read from DB_IMPORT_USER/DB_IMPORT_PASSWORD, never command args.
Statistics and ready publication are a separate, as-yet unimplemented step.
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

from cleaning.atlas_clean import FIELDS, ROOT
from database.preflight import check, json_lines


def utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Timestamp must include timezone")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


NULLABLE = {"province_key", "province_name", "city_key", "city_name", "grade_level", "price_min", "price_max", "currency", "price_basis", "price_policy_id", "price_raw"}


def attraction_values(row):
    return tuple(utc(row[f]) if f == "collected_at" else
        Decimal(row[f]) if f in ("price_min", "price_max") and row[f] else
        None if f in NULLABLE and row[f] == "" else
        json.loads(row[f]) if f in ("type_codes", "source_refs") else row[f] for f in FIELDS)


def equal_attractions(rows, stored):
    expected = {row["attraction_id"]: attraction_values(row) for row in rows}
    if len(expected) != len(rows) or len(stored) != len(rows):
        return False
    for dbrow in stored:
        values = list(dbrow)
        for field in ("type_codes", "source_refs"):
            index = FIELDS.index(field)
            values[index] = json.loads(values[index]) if isinstance(values[index], str) else values[index]
        if expected.get(values[1]) != tuple(values):
            return False
    return True


def equal_evidence(evidence, stored):
    expected = {e["source_ref"]: e for e in evidence}
    if len(expected) != len(evidence) or len(stored) != len(evidence):
        return False
    for ref, source_id, item_id, url, collected, date, kind, raw_ref, payload in stored:
        e = expected.get(ref)
        if e is None or (source_id, item_id, url, collected, date, kind, raw_ref) != (
                e["source_id"], e.get("source_item_id"), e["source_url"], utc(e["collected_at"]),
                e.get("source_date"), e["source_date_kind"], e["raw_ref"]):
            return False
        if (json.loads(payload) if isinstance(payload, str) else payload) != e:
            return False
    return True


def run(batch_id):
    import pymysql

    result = check(batch_id)
    metadata = ROOT / "data/metadata" / batch_id
    manifest = json.loads((metadata / "manifest.json").read_text(encoding="utf-8"))
    dictionaries = json.loads((metadata / "dictionaries.json").read_text(encoding="utf-8"))
    sources = json_lines(metadata / "sources.jsonl")
    evidence = json_lines(metadata / "evidence.jsonl")
    standard = ROOT / manifest["standard_file"]
    with standard.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    user = os.environ.get("DB_IMPORT_USER")
    password = os.environ.get("DB_IMPORT_PASSWORD")
    if not user or password is None:
        raise ValueError("Set DB_IMPORT_USER and DB_IMPORT_PASSWORD in the local environment")
    dbname = os.environ.get("DB_NAME", "tourism_recommender")
    connection_options = dict(user=user, password=password, database=dbname, charset="utf8mb4", autocommit=False)
    socket = os.environ.get("DB_UNIX_SOCKET")
    if socket:
        connection_options["unix_socket"] = socket
    else:
        connection_options.update(host=os.environ.get("DB_HOST", "127.0.0.1"), port=int(os.environ.get("DB_PORT", "3306")))
    connection = pymysql.connect(**connection_options)
    encode = lambda value: json.dumps(value, ensure_ascii=False, allow_nan=False)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET time_zone = '+00:00'")
            cursor.execute("SET SESSION sql_mode = 'STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION'")
            cursor.execute("SELECT contract_version, standard_sha256, manifest_json, dictionaries_json, sources_json, state FROM dataset_batches WHERE batch_id=%s FOR UPDATE", (batch_id,))
            existing = cursor.fetchone()
            if existing:
                version, sha, saved_manifest, saved_dict, saved_sources, state = existing
                if (version != manifest["contract_version"] or sha != manifest["standard_sha256"]
                        or json.loads(saved_manifest) != manifest or json.loads(saved_dict) != dictionaries
                        or json.loads(saved_sources) != sources or state not in ("loading", "ready")):
                    raise ValueError("Existing batch differs or is failed; never overwrite it")
                cursor.execute("SELECT " + ",".join(FIELDS) + " FROM attractions WHERE batch_id=%s", (batch_id,))
                if not equal_attractions(rows, cursor.fetchall()):
                    raise ValueError("Existing attractions differ; never overwrite")
                cursor.execute("SELECT source_ref,source_id,source_item_id,source_url,collected_at,source_date,source_date_kind,raw_ref,payload_json FROM source_records WHERE batch_id=%s", (batch_id,))
                if not equal_evidence(evidence, cursor.fetchall()):
                    raise ValueError("Existing source records differ; never overwrite")
                connection.rollback()
                return dict(result, database_connected=True, imported=True, repeated=True, state=state)
            cursor.execute("INSERT INTO dataset_batches (batch_id,contract_version,standard_sha256,manifest_json,dictionaries_json,sources_json,state) VALUES (%s,%s,%s,%s,%s,%s,'loading')",
                (batch_id, manifest["contract_version"], manifest["standard_sha256"], encode(manifest), encode(dictionaries), encode(sources)))
            source_values = [(batch_id, e["source_ref"], e["source_id"], e.get("source_item_id"), e["source_url"],
                utc(e["collected_at"]), e.get("source_date"), e["source_date_kind"], e["raw_ref"], encode(e)) for e in evidence]
            cursor.executemany("INSERT INTO source_records (batch_id,source_ref,source_id,source_item_id,source_url,collected_at,source_date,source_date_kind,raw_ref,payload_json) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", source_values)
            values = [tuple(encode(value) if f in ("type_codes", "source_refs") else value
                for f, value in zip(FIELDS, attraction_values(row))) for row in rows]
            cursor.executemany("INSERT INTO attractions (" + ",".join(FIELDS) + ") VALUES (" + ",".join(["%s"] * len(FIELDS)) + ")", values)
            cursor.execute("SELECT " + ",".join(FIELDS) + " FROM attractions WHERE batch_id=%s", (batch_id,))
            if not equal_attractions(rows, cursor.fetchall()):
                raise ValueError("Imported attraction content mismatch")
            cursor.execute("SELECT source_ref,source_id,source_item_id,source_url,collected_at,source_date,source_date_kind,raw_ref,payload_json FROM source_records WHERE batch_id=%s", (batch_id,))
            if not equal_evidence(evidence, cursor.fetchall()):
                raise ValueError("Imported evidence content mismatch")
        connection.commit()
        return dict(result, database_connected=True, imported=True, repeated=False, state="loading")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1]), ensure_ascii=False, indent=2))
