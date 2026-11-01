import re
from .adapters.registry import normalize_key


CRITICAL_SPECS = ("model", "sku", "mpn", "gtin", "ram", "memory", "storage", "ssd", "processor", "cpu", "gpu", "screen", "size", "colour", "color")
TITLE_SIMILARITY_THRESHOLD = 0.80
COLOR_ALIASES = {"grey": "gray"}
TITLE_COLORS = {"black", "white", "blue", "silver", "gold", "pink", "green", "purple", "red", "orange", "teal", "lavender", "sage", "midnight", "starlight", "ultramarine", "graphite", "titanium", "natural", "desert", "violet", "yellow", "gray", "grey", "brown", "cream"}
MODEL_VARIANTS = {"pro", "max", "plus", "mini", "air", "ultra", "fold", "flip", "lite", "edge", "fe", "se"}
MODEL_FAMILIES = ("iphone", "pixel", "ipad", "macbook", "galaxy", "xperia", "oneplus", "redmi", "poco", "oppo", "vivo")
RETAILER_NAMES = {"shopsy", "flipkart", "amazon", "amazonindia", "meesho", "croma", "ajio", "myntra"}
ACCESSORY_PATTERNS = {
    "phone_case": re.compile(r"\b(?:case|cover|shell|skin|back cover|flip cover|pouch|sleeve|bumper|housing)\b", re.I),
    "screen_protector": re.compile(r"\b(?:screen protector|screen guard|tempered glass|lens protector|privacy glass|film)\b", re.I),
    "charger": re.compile(r"\b(?:charger|charging adapter|power adapter|adapter|wall charger|fast charger|power bank|powerbank)\b", re.I),
    "cable": re.compile(r"\b(?:charging cable|usb cable|type c cable|lightning cable|data cable|cord|wire)\b", re.I),
    "audio": re.compile(r"\b(?:earbuds|earbud|earphones|earphone|headphones|headphone|headset|earpods|airpods|airpod|tws|neckband|buds|wireless buds|in-ear)\b", re.I),
    "wearable": re.compile(r"\b(?:smartwatch|smart watch|smart band|watch strap|wristband|fitness band)\b", re.I),
    "holder": re.compile(r"\b(?:stand|holder|mount|car mount|tripod|gimbal)\b", re.I),
}


def _title_tokens(value: str) -> set[str]:
    normalized = re.sub(r"\b(\d+)\s+(gb|tb|mb)\b", r"\1\2", str(value or "").lower())
    return {token for token in re.findall(r"[a-z0-9]+", normalized) if token not in {"buy", "online", "from", "at", "croma"}}


def _title_attributes(value: str) -> dict[str, set[str]]:
    title = str(value or "")
    tokens = _title_tokens(title)
    # Ignore explicitly labelled RAM amounts when comparing storage capacities.
    ram_spans = [m.span(1) for m in re.finditer(r"\b(?:ram|memory)\s*[: -]?\s*(\d+(?:\.\d+)?\s*(?:gb|tb))\b", title, re.I)]
    ram_spans += [m.span(1) for m in re.finditer(r"\b(\d+(?:\.\d+)?\s*(?:gb|tb))\s*(?:ram|memory)\b", title, re.I)]
    storage = set()
    for match in re.finditer(r"\b(\d+(?:\.\d+)?\s*(?:gb|tb))\b", title, re.I):
        if not any(start <= match.start(1) < end for start, end in ram_spans):
            storage.add(re.sub(r"\s+", "", match.group(1)).lower())
    colors = {COLOR_ALIASES.get(token, token) for token in tokens & TITLE_COLORS}
    model_keys = set()
    family_pattern = "|".join(MODEL_FAMILIES)
    for match in re.finditer(rf"\b({family_pattern})\s*([a-z]?\d+[a-z]?)\b", title, re.I):
        model_keys.add(normalize_key(match.group(1) + match.group(2)))
    variants = tokens & MODEL_VARIANTS
    accessory_types = {kind for kind, pattern in ACCESSORY_PATTERNS.items() if pattern.search(title)}
    return {"storage": storage, "colors": colors, "model_keys": model_keys,
            "variants": variants, "accessory_types": accessory_types, "tokens": tokens}


def _spec_variant_values(product: dict, kind: str) -> set[str]:
    result = set()
    for key, value in (product.get("specs") or {}).items():
        label = str(key).lower()
        if kind == "storage" and any(term in label for term in ("storage", "capacity", "rom", "ssd")) and "ram" not in label:
            result.update(re.sub(r"\s+", "", item).lower() for item in re.findall(r"\d+(?:\.\d+)?\s*(?:gb|tb)", str(value), re.I))
        if kind == "colors" and ("color" in label or "colour" in label):
            result.update(COLOR_ALIASES.get(item.lower(), item.lower()) for item in re.findall(r"[a-z]+", str(value), re.I) if item.lower() in TITLE_COLORS)
    return result


BRAND_EQUIVALENTS = {
    "iphone": "apple",
    "ipad": "apple",
    "macbook": "apple",
    "airpods": "apple",
    "earpods": "apple",
    "galaxy": "samsung",
    "pixel": "google",
    "playstation": "sony",
    "xbox": "microsoft",
    "redmi": "xiaomi",
    "mi": "xiaomi",
    "poco": "xiaomi",
}


def _brand_key(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", str(value or "").lower())
    while words and words[-1] in {"inc", "ltd", "limited", "corp", "corporation", "company", "co"}:
        words.pop()
    key = "".join(words)
    return BRAND_EQUIVALENTS.get(key, key)


def _same_variant_title(left: dict, right: dict) -> bool:
    return (len(left["tokens"]) >= 5 and left["tokens"] == right["tokens"]
            and bool(left["storage"]) and bool(left["colors"]))


def match_product(anchor: dict, candidate: dict) -> dict:
    evidence, conflicts, missing = [], [], []
    a_brand, b_brand = anchor.get("brand"), candidate.get("brand")
    a_title = _title_attributes(anchor.get("title", ""))
    b_title = _title_attributes(candidate.get("title", ""))

    if a_brand and b_brand:
        a_key, b_key = _brand_key(a_brand), _brand_key(b_brand)
        if a_key != b_key:
            # If the candidate's brand is a retailer name (e.g. Shopsy/Flipkart), verify from title
            if b_key in RETAILER_NAMES and a_key in {normalize_key(t) for t in b_title["tokens"]}:
                evidence.append(f"brand verified from title ({a_brand})")
            elif a_key in RETAILER_NAMES and b_key in {normalize_key(t) for t in a_title["tokens"]}:
                evidence.append(f"brand verified from title ({b_brand})")
            elif a_title["model_keys"] and a_title["model_keys"] == b_title["model_keys"] and (a_key in {normalize_key(t) for t in b_title["tokens"]} or b_key in {normalize_key(t) for t in a_title["tokens"]}):
                evidence.append(f"brand verified from model family ({a_brand} / {b_brand})")
            else:
                conflicts.append("brand differs")
        else:
            evidence.append("brand matches")

    a_ids, b_ids = anchor.get("identifiers", {}), candidate.get("identifiers", {})
    exact_id = False
    exact_gtin = False
    for key in ("gtin", "mpn", "sku"):
        left, right = a_ids.get(key), b_ids.get(key)
        if left and right:
            if normalize_key(left) != normalize_key(right):
                conflicts.append(f"{key} differs")
            else:
                evidence.append(f"exact {key}")
                exact_id = True
                exact_gtin = exact_gtin or key == "gtin"

    if anchor.get("model") and candidate.get("model"):
        if normalize_key(anchor["model"]) == normalize_key(candidate["model"]):
            evidence.append("model matches")
            exact_id = True
        else:
            conflicts.append("model differs")
    elif anchor.get("model"):
        if normalize_key(anchor["model"]) in normalize_key(candidate.get("title", "")):
            evidence.append(f"model matches in title ({anchor['model']})")
            exact_id = True
        elif a_title["model_keys"] and a_title["model_keys"] == b_title["model_keys"]:
            evidence.append(f"model matches in title ({', '.join(a_title['model_keys'])})")
            exact_id = True
        else:
            missing.append("model")
    elif a_title["model_keys"] and b_title["model_keys"]:
        if a_title["model_keys"] == b_title["model_keys"]:
            evidence.append(f"model matches in title ({', '.join(a_title['model_keys'])})")
            exact_id = True

    a_specs, b_specs = anchor.get("specs", {}), candidate.get("specs", {})
    for key in CRITICAL_SPECS:
        left, right = a_specs.get(key), b_specs.get(key)
        if left and right:
            if normalize_key(str(left)) != normalize_key(str(right)):
                conflicts.append(f"{key} differs")
            else:
                evidence.append(f"{key} matches")
        elif left and key in ("model", "sku", "mpn", "gtin", "ram", "storage", "ssd", "processor", "cpu", "gpu", "screen", "size"):
            if key == "model" and exact_id:
                pass
            else:
                missing.append(key)

    a_storage = a_title["storage"] | _spec_variant_values(anchor, "storage")
    b_storage = b_title["storage"] | _spec_variant_values(candidate, "storage")
    a_colors = a_title["colors"] | _spec_variant_values(anchor, "colors")
    b_colors = b_title["colors"] | _spec_variant_values(candidate, "colors")

    if a_title["model_keys"] and b_title["model_keys"] and a_title["model_keys"] != b_title["model_keys"]:
        conflicts.append("title model differs")
    if a_storage:
        if not b_storage:
            missing.append("storage")
        elif not a_storage.issubset(b_storage):
            conflicts.append("storage differs")
        else:
            evidence.append("storage matches in title or specifications")
            exact_id = exact_id or _same_variant_title(a_title, b_title) or (bool(a_title["model_keys"]) and a_title["model_keys"] == b_title["model_keys"])
            missing = [item for item in missing if item != "storage"]
    if a_colors:
        if not b_colors:
            missing.append("colour")
        elif not (a_colors & b_colors):
            conflicts.append("colour differs")
        else:
            evidence.append("colour matches in title or specifications")
            missing = [item for item in missing if item != "colour"]
    if a_title["variants"] != b_title["variants"]:
        if b_title["variants"]:
            conflicts.append("model variant differs")
        elif a_title["variants"]:
            missing.append("model variant")
    if a_title["accessory_types"] != b_title["accessory_types"]:
        if a_title["accessory_types"] or b_title["accessory_types"]:
            conflicts.append("product type differs (accessory or main product)")

    variant_evidence = any(item.startswith(tuple(f"{key} matches" for key in CRITICAL_SPECS if key not in ("model", "sku", "mpn", "gtin"))) for item in evidence)
    if not conflicts and _same_variant_title(a_title, b_title):
        evidence.append("exact model, storage, and colour title match")
        exact_id = True
        variant_evidence = True

    if not conflicts and exact_id and ("storage matches in title or specifications" in evidence) and (not a_colors or "colour matches in title or specifications" in evidence):
        variant_evidence = True

    if conflicts:
        classification = "non_match"
    elif exact_id and not missing and (exact_gtin or variant_evidence):
        classification = "exact"
    elif exact_id:
        classification = "probable"
    else:
        overlap = len(a_title["tokens"] & b_title["tokens"]) / max(len(a_title["tokens"]), 1)
        anchor_numbers = {token for token in a_title["tokens"] if token.isdigit()}
        candidate_numbers = {token for token in b_title["tokens"] if token.isdigit()}
        if overlap == 0 or (anchor_numbers and not anchor_numbers.issubset(candidate_numbers)):
            classification = "non_match"
        else:
            classification = "probable" if overlap >= TITLE_SIMILARITY_THRESHOLD else "uncertain"
            evidence.append(f"title token overlap {overlap:.2f}; candidate evidence only")
    return {"classification": classification, "evidence": evidence, "missing": sorted(set(missing)), "conflicts": sorted(set(conflicts))}
