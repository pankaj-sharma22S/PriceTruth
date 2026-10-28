from app.matching import match_product


def test_exact_identifier_and_same_variant():
    anchor = {"title": "Laptop Model X 16GB", "model": "Model-X", "identifiers": {"mpn": "Model-X"}, "specs": {"ram": "16GB", "storage": "512GB"}}
    result = match_product(anchor, {"title": "Laptop Model X 16GB", "model": "Model-X", "identifiers": {"mpn": "Model-X"}, "specs": {"ram": "16GB", "storage": "512GB"}})
    assert result["classification"] == "exact"


def test_variant_conflict_is_not_comparable():
    anchor = {"title": "Laptop Model X 16GB", "model": "Model-X", "identifiers": {"mpn": "Model-X"}, "specs": {"ram": "16GB", "storage": "512GB"}}
    candidate = {"title": "Laptop Model X 8GB", "model": "Model-X", "identifiers": {"mpn": "Model-X"}, "specs": {"ram": "8GB", "storage": "512GB"}}
    assert match_product(anchor, candidate)["classification"] == "non_match"


def test_missing_variant_fields_stays_probable():
    anchor = {"title": "Laptop Model X", "model": "Model-X", "identifiers": {"mpn": "Model-X"}, "specs": {"ram": "16GB"}}
    candidate = {"title": "Laptop Model X", "model": "Model-X", "identifiers": {"mpn": "Model-X"}, "specs": {}}
    assert match_product(anchor, candidate)["classification"] == "probable"


def test_exact_gtin_does_not_override_missing_critical_variant():
    anchor = {"title": "Laptop Model X 16GB", "identifiers": {"gtin": "1234567890123"}, "specs": {"ram": "16GB"}}
    candidate = {"title": "Laptop Model X", "identifiers": {"gtin": "1234567890123"}, "specs": {}}
    result = match_product(anchor, candidate)
    assert result["classification"] == "probable"
    assert "ram" in result["missing"]


def test_exact_variant_title_normalizes_storage_and_retailer_wrapper():
    anchor = {"title": "Apple iPhone 17 (White, 256 GB)", "identifiers": {}, "specs": {}}
    candidate = {"title": "Buy Apple iPhone 17 (256GB, White) Online - Croma", "identifiers": {}, "specs": {}}
    result = match_product(anchor, candidate)
    assert result["classification"] == "exact"
    assert "exact model, storage, and colour title match" in result["evidence"]


def test_gtin_does_not_override_storage_or_colour_title_conflicts():
    anchor = {"title": "Apple iPhone 17 White 256 GB", "brand": "Apple", "identifiers": {"gtin": "1234567890123"}, "specs": {}}
    wrong_storage = {"title": "Apple iPhone 17 White 128 GB", "brand": "Apple Inc.", "identifiers": {"gtin": "1234567890123"}, "specs": {}}
    wrong_colour = {"title": "Apple iPhone 17 Black 256 GB", "brand": "Apple", "identifiers": {"gtin": "1234567890123"}, "specs": {}}
    assert match_product(anchor, wrong_storage)["classification"] == "non_match"
    assert match_product(anchor, wrong_colour)["classification"] == "non_match"


def test_gtin_does_not_override_a_missing_title_variant():
    anchor = {"title": "Apple iPhone 17 White 256 GB", "identifiers": {"gtin": "1234567890123"}, "specs": {}}
    candidate = {"title": "Apple iPhone 17", "identifiers": {"gtin": "1234567890123"}, "specs": {}}
    result = match_product(anchor, candidate)
    assert result["classification"] == "probable"
    assert {"storage", "colour"}.issubset(result["missing"])


def test_gtin_does_not_override_model_generation_or_accessory_type():
    anchor = {"title": "Apple iPhone 17 White 256 GB", "brand": "Apple", "identifiers": {"gtin": "1234567890123"}, "specs": {}}
    wrong_model = {"title": "Apple iPhone 17e White 256 GB", "brand": "Apple", "identifiers": {"gtin": "1234567890123"}, "specs": {}}
    accessory = {"title": "Apple iPhone 17 White 256 GB Case", "brand": "Apple", "identifiers": {"gtin": "1234567890123"}, "specs": {}}
    assert match_product(anchor, wrong_model)["classification"] == "non_match"
    assert match_product(anchor, accessory)["classification"] == "non_match"


def test_structured_brand_conflict_rejects_a_candidate():
    anchor = {"title": "Phone Model X White 256 GB", "brand": "Brand A", "identifiers": {"gtin": "1234567890123"}, "specs": {}}
    candidate = {"title": "Phone Model X White 256 GB", "brand": "Brand B", "identifiers": {"gtin": "1234567890123"}, "specs": {}}
    result = match_product(anchor, candidate)
    assert result["classification"] == "non_match"
    assert "brand differs" in result["conflicts"]
