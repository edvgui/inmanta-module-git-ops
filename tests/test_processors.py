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

import pytest
import yaml
from inmanta_plugins.example.slices import recursive
from pytest_inmanta.plugin import Project

from inmanta_plugins.git_ops import const, processors


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
        assert processors.used_values(recursive.STORE.name, "unique_id")() == [None]

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
            )()
        ) == {1, 2}
