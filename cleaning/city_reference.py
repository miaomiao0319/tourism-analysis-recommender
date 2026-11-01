"""Province-bound exact pinyin/Chinese aliases from a licensed reference snapshot."""
import re
import unicodedata
from collections import defaultdict


def roman(value):
    value = value.lower().replace("ü", "v")
    value = unicodedata.normalize("NFD", value)
    return re.sub("[^a-z]", "", value)


class CityReference:
    def __init__(self, rows, meta, raw_ref):
        self.english, self.chinese = defaultdict(set), defaultdict(set)
        self.records, self.evidence = {}, []
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

    def lookup(self, province, value, english=False):
        key = (province, roman(value) if english else value)
        refs = (self.english if english else self.chinese).get(key, set())
        if len(refs) != 1:
            return None
        ref = next(iter(refs))
        return self.records[ref], ref
