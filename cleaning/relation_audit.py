"""Triage linked destinations; lexical hints are never identity confirmation."""
import re


def review(groups, mappings, evidence):
    entities = {r["attraction_id"]: r for r in mappings}
    observations = {r["source_ref"]: r for r in evidence}
    result = []
    for index, group in enumerate(groups, 1):
        names = [name for aid in group for name in entities[aid]["name_aliases"]]
        refs = sorted({ref for aid in group for ref in entities[aid]["source_refs"]})
        rows = [observations[ref] for ref in refs]
        kind = "unresolved"
        if any("与" in name or "及" in name for name in names):
            kind = "combined_destination_scope_warning"
        else:
            for official in (r["raw"] for r in rows if r["source_id"] == "atlas_5a"):
                short = official["name_zh"]
                prefecture = official.get("prefecture", "")
                if prefecture and short.startswith(prefecture):
                    short = short[len(prefecture):]
                short = re.sub(r"(?:旅游景区|风景名胜区|风景区|旅游区|景区)$", "", short)
                if short in names:
                    kind = "possible_name_variant_not_confirmed"
                elif any(name in short for name in names if name != official["name_zh"]):
                    kind = "possible_subarea_scope_warning"
        result.append(dict(review_id=f"rel_{index}", attraction_ids=group, names=names,
            source_refs=refs, triage=kind, confirmed_same_entity=False,
            action="keep_separate_pending_geographic_scope_and_identity_evidence"))
    return result
