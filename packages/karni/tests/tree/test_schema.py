"""x-karni-tree and the tree operations in the OpenAPI document."""

from __future__ import annotations

from typing import Any

import pytest
from drf_spectacular.drainage import GENERATOR_STATS
from drf_spectacular.generators import SchemaGenerator

TREE = {"parent": "parent", "ordered": False}
ORDERED = {"parent": "parent", "ordered": True}


@pytest.fixture(scope="module")
def generated() -> tuple[dict[str, Any], list[str]]:
    GENERATOR_STATS.reset()
    with GENERATOR_STATS.silence():
        schema = SchemaGenerator().get_schema(request=None, public=True)
    messages = [*GENERATOR_STATS._warn_cache, *GENERATOR_STATS._error_cache]
    GENERATOR_STATS.reset()
    return schema, messages


@pytest.fixture(scope="module")
def schema(generated: tuple[dict[str, Any], list[str]]) -> dict[str, Any]:
    return generated[0]


def components(schema: dict[str, Any]) -> dict[str, Any]:
    found: dict[str, Any] = schema["components"]["schemas"]
    return found


def test_generation_warns_about_nothing_tree_related(
    generated: tuple[dict[str, Any], list[str]],
) -> None:
    tree_words = ("Region", "Category", "Product", "tree", "Tree")
    assert [m for m in generated[1] if any(word in m for word in tree_words)] == []


def test_a_tree_models_component_carries_x_karni_tree(schema: dict[str, Any]) -> None:
    found = components(schema)
    assert found["TestappRegion"]["x-karni-tree"] == TREE
    assert found["TestappCategory"]["x-karni-tree"] == ORDERED
    assert found["TestappRegionTreeNode"]["x-karni-tree"] == TREE
    assert "x-karni-tree" not in found["TestappVenue"]
    assert "x-karni-tree" not in found["TestappProduct"]


def test_every_relation_to_a_tree_carries_x_karni_tree(schema: dict[str, Any]) -> None:
    product = components(schema)["TestappProduct"]["properties"]
    assert product["category"]["x-karni-tree"] == ORDERED
    assert product["category"]["x-karni-relation"] == {"resource": "categories", "many": False}
    assert product["regions"]["x-karni-tree"] == TREE
    assert product["regions"]["x-karni-relation"] == {"resource": "regions", "many": True}
    assert components(schema)["TestappRegion"]["properties"]["parent"]["x-karni-tree"] == TREE
    event = components(schema)["TestappEvent"]["properties"]
    assert "x-karni-tree" not in event["venue"]


def test_the_tree_node_nests_itself(schema: dict[str, Any]) -> None:
    node = components(schema)["TestappRegionTreeNode"]
    children = node["properties"]["children"]
    assert children["type"] == "array" and children["nullable"] is True
    assert children["items"] == {"$ref": "#/components/schemas/TestappRegionTreeNode"}
    assert node["properties"]["has_children"]["type"] == "boolean"
    tree = components(schema)["TestappRegionTree"]["properties"]
    assert tree["results"]["items"] == {"$ref": "#/components/schemas/TestappRegionTreeNode"}
    assert tree["truncated"]["type"] == "boolean"


def test_only_tree_resources_have_tree_operations(schema: dict[str, Any]) -> None:
    paths = schema["paths"]
    for resource in ("regions", "categories"):
        assert f"/api/{resource}/tree/" in paths
        for action in ("children", "ancestors", "move"):
            assert f"/api/{resource}/{{id}}/{action}/" in paths
    assert not [path for path in paths if path.startswith("/api/venues/") and "tree" in path]
    tree = paths["/api/regions/tree/"]["get"]
    assert {param["name"] for param in tree["parameters"]} == {"root", "depth"}
    children = paths["/api/regions/{id}/children/"]["get"]
    assert {param["name"] for param in children["parameters"]} == {"id", "page", "page_size"}
    ancestors = paths["/api/regions/{id}/ancestors/"]["get"]["responses"]["200"]
    assert ancestors["content"]["application/json"]["schema"]["type"] == "array"
    delete = paths["/api/regions/{id}/"]["delete"]
    assert "branch" in {param["name"] for param in delete["parameters"]}
    venue_delete = paths["/api/venues/{id}/"]["delete"]
    assert "branch" not in {param["name"] for param in venue_delete.get("parameters", [])}
    listed = {param["name"] for param in paths["/api/regions/"]["get"]["parameters"]}
    assert {"parent", "descendants_of"} <= listed


def test_move_takes_a_parent_and_a_position(schema: dict[str, Any]) -> None:
    move = schema["paths"]["/api/categories/{id}/move/"]["post"]
    ref = move["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    body = components(schema)[ref.rsplit("/", 1)[-1]]
    assert set(body["properties"]) == {"parent", "position"}
    assert body["properties"]["parent"]["nullable"] is True
    assert move["x-karni-access"] == {"role": ["staff"]}


def test_an_ordered_trees_position_is_read_only(schema: dict[str, Any]) -> None:
    found = components(schema)
    assert found["TestappCategory"]["properties"]["position"]["readOnly"] is True
    assert "position" not in found["TestappCategoryRequest"]["properties"]
