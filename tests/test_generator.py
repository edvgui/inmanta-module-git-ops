"""
Copyright 2026 Guillaume Everarts de Velp

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Contact: edvgui@gmail.com
"""

from inmanta_module_factory.inmanta import Index
from inmanta_plugins.example.slices.fs import RootFolder

from inmanta_git_ops import generator


def test_index_field_order_matches_keys() -> None:
    """
    The generated index of an entity must list its fields in the exact order in
    which the keys are declared on the slice schema.

    The generator used to build the index by iterating ``entity.all_fields()``,
    which returns a set: the resulting field order was arbitrary and unstable
    from one generation to the next.  RootFolder declares its keys as
    ``["root", "name"]`` where ``root`` is defined on the entity itself and
    ``name`` is inherited, a case where the set iteration order is very unlikely
    to match the declared order.
    """
    schema = RootFolder.entity_schema()
    assert list(schema.keys) == ["root", "name"]

    entity = generator.get_entity(schema, slice_root=True)

    builder = generator.get_module_builder("example")
    indexes = [
        element
        for element in builder._model_files[entity.path_string]
        if isinstance(element, Index) and element.entity is entity
    ]
    assert len(indexes) == 1

    assert [field.name for field in indexes[0].fields] == list(schema.keys)
