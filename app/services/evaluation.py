import re

INLINE_CITATION_PATTERN = re.compile(r"\[(S\d+-F\d+)\]")
CITATION_ID_PATTERN = re.compile(r"^S(\d+)-F(\d+)$")
SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")
MISSING_SENTENCE_SPACE_PATTERN = re.compile(r'(?<=[a-z0-9\])"])([.!?])(?=[A-Z])')

REQUIRED_CITATION_FIELDS = {
    "item_id",
    "fact_number",
    "source_name",
    "headline",
    "url",
    "claim",
    "supporting_excerpt",
}


def extract_citation_ids(body: str) -> list[str]:
    """
    Returns citation IDs in the order they appear in the article body.
    Example:
    "Google changed Search [S4-F1]." -> ["S4-F1"]
    """
    return INLINE_CITATION_PATTERN.findall(body)


def validate_citation_map(citation_map: dict[str, dict]) -> list[str]:
    """
    Returns human-readable errors for malformed evidence-map entries.
    An empty list means the snapshot is structurally valid.
    """
    errors = []

    for citation_id, evidence in citation_map.items():
        match = CITATION_ID_PATTERN.fullmatch(citation_id)

        if not match:
            errors.append(f"{citation_id}: invalid citation ID format")
            continue

        if not isinstance(evidence, dict):
            errors.append(f"{citation_id}: evidence entry must be an object")
            continue

        missing_fields = REQUIRED_CITATION_FIELDS - evidence.keys()
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            errors.append(f"{citation_id}: missing required fields: {missing}")
            continue

        empty_fields = [
            field
            for field in REQUIRED_CITATION_FIELDS
            if evidence[field] in (None, "", [])
        ]
        if empty_fields:
            empty = ", ".join(sorted(empty_fields))
            errors.append(f"{citation_id}: empty required fields: {empty}")

        item_id_from_key = int(match.group(1))
        fact_number_from_key = int(match.group(2))

        if evidence["item_id"] != item_id_from_key:
            errors.append(
                f"{citation_id}: item_id does not match the citation ID"
            )

        if evidence["fact_number"] != fact_number_from_key:
            errors.append(
                f"{citation_id}: fact_number does not match the citation ID"
            )

    return errors


def validate_citation_ids(citation_ids: list[str], citation_map: dict[str, dict], ) -> list[str]:
    """
    Returns unique citation IDs used by the article but missing from its map.
    """
    return sorted({
        citation_id
        for citation_id in citation_ids
        if citation_id not in citation_map
    })


def build_sentence_records(body: str) -> list[dict]:
    """
    Splits the article into traceable sentences and preserves each sentence's
    inline citation IDs.
    """
    body = MISSING_SENTENCE_SPACE_PATTERN.sub(r"\1 ", body)

    sentences = [
        sentence.strip()
        for sentence in SENTENCE_BOUNDARY_PATTERN.split(body.strip())
        if sentence.strip()
    ]

    return [
        {
            "sentence_index": index,
            "sentence_text": sentence,
            "citation_ids": extract_citation_ids(sentence),
        }
        for index, sentence in enumerate(sentences)
    ]
