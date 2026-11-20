from data.demo.schemas import convert_fragment, product_schema


def test_integer_and_nested_metadata_are_converted_without_weakening_constraints():
    converted = convert_fragment({"type": "object", "$schema": "removed", "properties": {
        "type": {"type": "integer", "minimum": 1, "maximum": 9, "format": "int32"},
        "nested": {"type": "object", "$id": "removed", "properties": {"enabled": {"type": "boolean"}}},
    }, "additionalProperties": False})
    assert converted["properties"]["type"] == {"bsonType": ["int", "long"], "minimum": 1, "maximum": 9}
    assert converted["properties"]["nested"] == {
        "bsonType": "object", "properties": {"enabled": {"bsonType": "bool"}},
    }
    assert "$schema" not in converted and converted["additionalProperties"] is False


def test_fixture_attributes_and_dataset_attributes_form_a_strict_union():
    existing = {"bsonType": "object", "properties": {"attributes": {"bsonType": "object",
        "required": ["author", "isbn"], "additionalProperties": False,
        "properties": {"author": {"bsonType": "string"}, "isbn": {"bsonType": "string", "pattern": "isbn-pattern"}}}}}
    source = {"properties": {"attributes": {"type": "object", "required": ["page_count"],
        "additionalProperties": False, "properties": {"page_count": {"type": "integer", "minimum": 16}}}}}
    schema = product_schema("books", source, existing)
    attrs = schema["properties"]["attributes"]
    assert not attrs.get("required")
    assert attrs["properties"]["isbn"]["pattern"] == "isbn-pattern"
    assert attrs["properties"]["page_count"]["bsonType"] == ["int", "long"]
    assert attrs["additionalProperties"] is False
    assert schema["properties"]["category"] == {"enum": ["books"]}
