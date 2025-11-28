"""
Copyright 2025 Guillaume Everarts de Velp

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

import json
import pathlib

from inmanta_plugins.example.slices import fs, recursive, simple

from inmanta.module import ModuleV2
from inmanta_plugins.git_ops import generator


def test_basics() -> None:
    example_path = pathlib.Path(__file__).parent.parent / "docs/example"

    example = ModuleV2.from_path(str(example_path))
    assert example is not None
    example._is_editable_install = True

    # Preload cache with entity of git_ops module and generate module base entity
    git_ops_builder = generator.get_module_builder("git_ops")
    git_ops_builder.upgrade_existing_module(
        generator.get_module("git_ops"), fix_linting=False
    )

    # Generate the model for the slices defined in the example module
    example_builder = generator.get_module_builder("example")
    generator.get_entity(simple.Slice.entity_schema(), slice_root=True)
    generator.get_entity(recursive.Slice.entity_schema(), slice_root=True)
    generator.get_entity(fs.RootFolder.entity_schema(), slice_root=True)

    example_builder.upgrade_existing_module(example, fix_linting=False)

    # Generate openapi definitions
    schema_file = example_path / "files/slices/fs.json"
    schema_file.parent.mkdir(parents=True, exist_ok=True)
    schema_file.write_text(json.dumps(fs.RootFolder.model_json_schema(), indent=2))
