"""Unit tests for Rhino layer filtering logic."""

import sys
from pathlib import Path

from specklepy.objects import Base

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import _iter_base_with_inherited_layers, _matches_layer


def _obj_with_layer(layer_name: str, attr: str = "layer") -> Base:
    obj = Base()
    if attr == "layer":
        obj.layer = layer_name
    elif attr == "Layer":
        obj.Layer = layer_name
    else:
        props = Base()
        props.layer = layer_name
        obj.properties = props
    return obj


def test_matches_exact_full_path_layer() -> None:
    obj = _obj_with_layer("3D-Model::Structure::Floor Plate Curve")
    assert _matches_layer(obj, "3D-Model::Structure::Floor Plate Curve")


def test_matches_leaf_when_filter_has_full_path() -> None:
    obj = _obj_with_layer("Floor Plate Curve")
    assert _matches_layer(obj, "3D-Model::Structure::Floor Plate Curve")


def test_matches_leaf_when_object_has_full_path() -> None:
    obj = _obj_with_layer("3D-Model::Structure::Floor Plate Curve")
    assert _matches_layer(obj, "Floor Plate Curve")


def test_matches_layer_from_properties_or_capital_layer() -> None:
    obj_props = _obj_with_layer("3D-Model::Structure::Floor Plate Curve", attr="properties")
    obj_cap = _obj_with_layer("3D-Model::Structure::Floor Plate Curve", attr="Layer")

    assert _matches_layer(obj_props, "Floor Plate Curve")
    assert _matches_layer(obj_cap, "Floor Plate Curve")


def test_returns_false_for_different_layer() -> None:
    obj = _obj_with_layer("3D-Model::Architecture::Facade")
    assert not _matches_layer(obj, "3D-Model::Structure::Floor Plate Curve")


def test_inherits_layer_name_from_parent_collection() -> None:
    root = Base()

    collection = Base()
    collection.speckle_type = "Objects.Organization.Collection"
    collection.collectionType = "Layer"
    collection.name = "3D-Model::Structure::Floor Plate Curve"

    curve = Base()
    curve.speckle_type = "Objects.Geometry.Curve"
    collection["@elements"] = [curve]
    root["@elements"] = [collection]

    inherited = list(_iter_base_with_inherited_layers(root))
    curve_entry = next((layers for obj, layers in inherited if obj is curve), set())

    assert "3D-Model::Structure::Floor Plate Curve" in curve_entry
