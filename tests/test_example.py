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
from inmanta_plugins.example.slices import fs
from pytest_inmanta.plugin import Project

from inmanta_plugins.git_ops import const


def test_fs(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    imports = [
        "example::slices::fs",
        "example::slices::fs::unroll",
    ]

    model = "\n".join(f"import {i}" for i in imports)

    # Empty compile
    project.compile(model)
    assert not project.get_instances("example::slices::fs::RootFolder")

    # Create a first folder slice
    f1 = fs.RootFolder(
        root="/tmp",
        name="test1",
        files=[
            fs.File(
                name="a.txt",
                content="a",
            ),
        ],
        directories=[
            fs.Folder(
                name="b",
                files=[
                    fs.File(
                        name="b.txt",
                        content="b",
                    ),
                ],
                directories=[
                    fs.Folder(
                        name="c",
                    ),
                ],
            )
        ],
    )
    f1_path = fs.STORE.source_path / "f1.yaml"
    f1_path.parent.mkdir(parents=True, exist_ok=True)
    f1_path.write_text(yaml.safe_dump(f1.model_dump(mode="json")))

    # Export compile with one slice, still empty
    project.compile(model)
    assert not project.get_instances("example::slices::fs::RootFolder")

    # Add the slice to the active store
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_SYNC)
        project.compile(model)

    # We should now have one root folder in the model
    assert len(project.get_instances("example::slices::fs::RootFolder")) == 1

    # Get the content of file a.txt
    file_a = next(
        f
        for f in project.get_instances("example::slices::fs::File")
        if f.name == "a.txt"
    )
    assert file_a.content == "a"
    assert file_a.previous_content is None

    # Update the content of file a
    f1.files[0].content = "aa"
    f1_path.write_text(yaml.safe_dump(f1.model_dump(mode="json")))

    # Add the slice to the active store
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_SYNC)
        project.compile(model)

    # Get the content of file a.txt
    file_a = next(
        f
        for f in project.get_instances("example::slices::fs::File")
        if f.name == "a.txt"
    )
    assert file_a.content == "aa"
    assert file_a.previous_content == "a"
