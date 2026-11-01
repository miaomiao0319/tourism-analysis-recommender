"""Province-bound exact pinyin/Chinese aliases from a licensed reference snapshot."""
import re
import unicodedata
from collections import defaultdict


def roman(value):
    value = value.lower().replace("ü", "v")
    value = unicodedata.normalize("NFD", value)
    return re.sub("[^a-z]", "", value)


class CityReference:
    def __init__(self, rows, meta, raw_ref, wanted=(), wanted_names=()):
        self.english, self.chinese = defaultdict(set), defaultdict(set)
        self.lower = defaultdict(set)
        self.prefixes = defaultdict(set)
        self.records, self.evidence, self.targets = {}, [], {}
        for index, row in enumerate(rows, 1):
            # This package promotes directly administered counties to level=1;
            # six-digit counties must not become prefecture-level cities here.
            if row["level"] != 1 or not re.fullmatch(r"\d{4}", row["code"]):
                continue
            if not row["fullName"].endswith(("市", "自治州", "地区", "盟")):
                continue
            code = row["parentCode"] + "0000"
            ref = "d_" + row["code"]
            self.records[ref] = row["fullName"]
            self.targets[ref] = row["code"]
            self.english[(code, roman(row["pinyin"]))].add(ref)
            if row["name"].endswith("市") and row["pinyin"].endswith(" shi"):
                self.english[(code, roman(row["pinyin"][:-4]))].add(ref)
            aliases = {row["name"], row["fullName"]}
            for suffix in ("地区", "市", "盟"):
                if row["fullName"].endswith(suffix):
                    aliases.add(row["fullName"][:-len(suffix)])
            if row["fullName"].endswith("自治州"):
                aliases.add(row["name"] + "州")
            for alias in aliases:
                self.chinese[(code, alias)].add(ref)
            self.evidence.append(dict(source_ref=ref, source_id="cn_divisions", source_item_id=row["code"],
                source_url=meta["url"], collected_at=meta["collected_at"], source_date=None, source_date_kind="unknown",
                raw_ref=f"{raw_ref}/divisions.raw#jsonl-line={index}", raw=row,
                record_role="dictionary_reference", snapshot_note="Undocumented upstream date; at least April 2023, not proof of 2026-10 validity"))
        by_code = {row["code"]: row for row in rows}
        for index, row in enumerate(rows, 1):
            if row["level"] not in (2, 3):
                continue
            province = row["code"][:2] + "0000"
            key = (province, roman(row["pinyin"]))
            prefix_match = any(province == p and name.startswith(row["fullName"]) for p, name in wanted_names)
            if key not in wanted and not prefix_match:
                continue
            current, chain = row, []
            while current["code"] not in chain:
                chain.append(current["code"])
                if current["level"] == 1 and len(current["code"]) == 4 and "d_" + current["code"] in self.records:
                    break
                current = by_code.get(current["parentCode"])
                if current is None:
                    break
            if current is None or current["level"] != 1 or len(current["code"]) != 4 or "d_" + current["code"] not in self.records:
                continue
            ref = "d_" + row["code"]
            self.records[ref] = current["fullName"]
            self.targets[ref] = current["code"]
            self.lower[key].add(ref)
            if prefix_match:
                self.prefixes[(province, row["fullName"])].add(ref)
            self.evidence.append(dict(source_ref=ref, source_id="cn_divisions", source_item_id=row["code"],
                source_url=meta["url"], collected_at=meta["collected_at"], source_date=None, source_date_kind="unknown",
                raw_ref=f"{raw_ref}/divisions.raw#jsonl-line={index}", raw=row, ancestor_codes=chain,
                resolved_prefecture=current["fullName"], record_role="dictionary_reference",
                snapshot_note="County/town gateway mapped via explicit parent chain; never fills a province-direct county with a guessed city"))

    def lookup_prefix(self, province, name):
        matches = [(prefix, refs) for (p, prefix), refs in self.prefixes.items() if p == province and name.startswith(prefix)]
        if not matches:
            return None
        longest = max(len(prefix) for prefix, _ in matches)
        refs = {ref for prefix, values in matches if len(prefix) == longest for ref in values}
        if len({self.targets[ref] for ref in refs}) != 1:
            return None
        ref = sorted(refs)[0]
        return self.records[ref], ref

    def add_wikidata(self, entity, meta, raw_ref, wanted):
        values = lambda prop: [s["mainsnak"].get("datavalue", {}).get("value") for s in entity.get("claims", {}).get(prop, [])
                               if s.get("rank") != "deprecated" and "P582" not in s.get("qualifiers", {})]
        if not any(isinstance(v, dict) and v.get("id") == "Q148" for v in values("P17")):
            raise ValueError("Alias entity country not confirmed")
        codes = {re.sub(r"\s", "", v) for v in values("P442") if isinstance(v, str)}
        codes = {code for code in codes if re.fullmatch(r"\d{4}", code) and "d_" + code in self.records}
        if len(codes) != 1:
            raise ValueError("Alias administrative code missing or ambiguous")
        code = next(iter(codes))
        names = [entity.get("labels", {}).get("en", {}).get("value", "")]
        names += [a["value"] for a in entity.get("aliases", {}).get("en", [])]
        ref = "w_" + entity["id"]
        self.records[ref], self.targets[ref] = self.records["d_" + code], code
        for province, value in wanted:
            if province != code[:2] + "0000":
                continue
            matched = any(roman(value) == roman(name) or
                (name.lower().startswith(value.lower() + " ") and name.endswith(("Prefecture", "League", "City"))) for name in names)
            if matched:
                self.english[(province, roman(value))].add(ref)
        self.evidence.append(dict(source_ref=ref, source_id="wikidata_geography", source_item_id=entity["id"],
            source_url=meta["url"], collected_at=meta["collected_at"], source_date=entity.get("modified", "")[:10] or None,
            source_date_kind="updated" if entity.get("modified") else "unknown", raw_ref=raw_ref,
            raw=dict(labels=entity.get("labels", {}), aliases=entity.get("aliases", {}),
                     claims={k: entity["claims"].get(k, []) for k in ("P17", "P442")}),
            record_role="dictionary_reference", matched_division_code=code,
            snapshot_note="CC0 bilingual labels with code/country cross-check, not proof of historical administrative validity"))

    def lookup(self, province, value, english=False):
        key = (province, roman(value) if english else value)
        refs = (self.english if english else self.chinese).get(key, set())
        if english and not refs:
            refs = self.lower.get(key, set())
        if not refs or len({self.targets[ref] for ref in refs}) != 1:
            return None
        ref = sorted(refs)[0]
        return self.records[ref], ref
