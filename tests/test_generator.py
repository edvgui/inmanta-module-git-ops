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

import pathlib

from inmanta_module_factory.builder import InmantaModuleBuilder
from inmanta_module_factory.inmanta import Module
from inmanta_plugins.example.slices import recursive, simple

from inmanta_plugins.git_ops import generator, slice


def test_basics() -> None:
    example_path = pathlib.Path(__file__).parent.parent / "docs/example"

    generator.get_entity(
        slice.SliceObjectABC.entity_schema(),
        builder=InmantaModuleBuilder(Module("git_ops"), allow_watermark=True),
    )

    example = Module(name="example")
    builder = InmantaModuleBuilder(example, allow_watermark=True)

    # Generate the model for the slices defined in the example module
    s1 = generator.get_entity(simple.Slice.entity_schema(), builder=builder)
    s2 = generator.get_entity(recursive.Slice.entity_schema(), builder=builder)

    builder.generate_model_file(example_path / "model", s1.path_string)
    builder.generate_model_file(example_path / "model", s2.path_string)
