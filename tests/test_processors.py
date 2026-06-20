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

import pytest
import yaml
from inmanta_plugins.example.slices import recursive
from inmanta_plugins.example.slices.recursive import EmbeddedSlice, Slice
from pytest_inmanta.plugin import Project

from inmanta.plugins import Context
from inmanta_plugins.git_ops import attribute_processor, const, processors
from inmanta_plugins.git_ops.store import SliceStore


def test_fs(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    imports = [
        "example::slices::recursive",
    ]

    model = "\n".join(f"import {i}" for i in imports)

    # Empty compile
    project.compile(model)
    assert not project.get_instances("example::slices::recursive::Slice")

    # Create a first simple slice
    s1 = recursive.Slice(
        name="test1",
        embedded_required=recursive.EmbeddedSlice(
            name="a",
        ),
    )
    s1_path = recursive.STORE.source_path / "test1.yaml"
    s1_path.parent.mkdir(parents=True, exist_ok=True)
    s1_path.write_text(yaml.safe_dump(s1.model_dump(mode="json")))

    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_UPDATE)

        # Try to call the used_values plugin on the slice store
        assert processors.used_values(recursive.STORE.name, "unique_id")() == []

        # Assign an id to the first slice, it should now show up in used values
        s1.unique_id = 1
        s1_path.write_text(yaml.safe_dump(s1.model_dump(mode="json")))
        recursive.STORE.clear()
        assert processors.used_values(recursive.STORE.name, "unique_id")() == [1]

        # Getting the used values for a part of the service that doesn't exist
        # shouldn't cause any issue
        assert (
            processors.used_values(
                recursive.STORE.name, "embedded_optional.unique_id"
            )()
            == []
        )

        # Adding the optional value, the collector should pick it up too
        s1.embedded_optional = recursive.EmbeddedSlice(
            name="b",
            unique_id=2,
        )
        s1_path.write_text(yaml.safe_dump(s1.model_dump(mode="json")))
        recursive.STORE.clear()
        assert processors.used_values(
            recursive.STORE.name, "embedded_optional.unique_id"
        )() == [2]

        # Searching for multiple ids at the same time should give us all of them
        assert set(
            processors.join_used_values(
                processors.used_values(
                    recursive.STORE.name, "embedded_optional.unique_id"
                ),
                processors.used_values(recursive.STORE.name, "unique_id"),
                processors.used_values(
                    recursive.STORE.name, "embedded_sequence[name=a].unique_id"
                ),
                processors.used_values(
                    recursive.STORE.name, "embedded_sequence[baba=a].unique_id"
                ),
            )()
        ) == {1, 2}


def test_get_template_value(
    project: Project, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Define a basic store
    store = SliceStore(
        name="test_template",
        folder="file://" + str(tmp_path / "test"),
        schema=Slice,
    )

    # A jinja template that the processor should render, using a value passed
    # to it as keyword argument
    template = tmp_path / "greeting.j2"
    template.write_text("Hello {{ who }}")

    model = """
        import git_ops
        import git_ops::processors

        for slice in git_ops::unroll_slices("test_template"):
            git_ops::processors::get_template_value(
                slice["store_name"],
                slice["name"],
                "description",
                who="world",
            )
        end
    """

    # Add one slice whose description points to the template
    s1_obj = Slice(
        name="a",
        description="file://" + str(template),
        embedded_required=EmbeddedSlice(
            name="aa",
        ),
    )
    s1 = store.source_path / "s1.yaml"
    s1.parent.mkdir(parents=True, exist_ok=True)
    s1.write_text(yaml.safe_dump(s1_obj.model_dump(mode="json")))

    # The processor needs the compiler context to render the template, it should
    # be passed automatically as first positional argument
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_UPDATE)
        project.compile(model, no_dedent=False)

    # The template path should have been rendered and saved back in the slice
    assert yaml.safe_load(s1.read_text())["description"] == "Hello world"


def test_context_must_be_first_positional() -> None:
    # A Context argument is only supported as the first positional argument
    with pytest.raises(ValueError, match="first positional argument"):

        @attribute_processor
        def misplaced_context(
            store_name: str,
            name: str,
            path: str,
            context: Context,
            previous_value: object | None = None,
        ) -> object:
            return previous_value
