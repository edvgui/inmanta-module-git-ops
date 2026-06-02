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
import os
import pathlib
import subprocess

import yaml


def test_basics() -> None:
    example_path = pathlib.Path(__file__).parent.parent / "docs/example"

    # List stores
    stores = subprocess.check_output(
        ["git-ops", "module", "store", "list", "--format", "json"],
        env={"INMANTA_GIT_OPS_MODULE_PATH": str(example_path), **os.environ},
        text=True,
    )
    assert len(json.loads(stores)) == 3

    # Test generation of the model
    subprocess.run(
        ["git-ops", "module", "generate", "--explicit-parent-relations"],
        check=True,
        env={"INMANTA_GIT_OPS_MODULE_PATH": str(example_path), **os.environ},
    )

    # Generate openapi definitions
    subprocess.run(
        ["git-ops", "module", "store", "schema", "--store", "fs"],
        check=True,
        env={"INMANTA_GIT_OPS_MODULE_PATH": str(example_path), **os.environ},
    )


def test_project_slice_commands(tmp_path: pathlib.Path) -> None:
    # Set up a minimal inmanta project using the example module, the modules
    # are resolved from the python environment running the test
    project_path = tmp_path / "project"
    project_path.mkdir()
    (project_path / "project.yml").write_text(yaml.safe_dump({"name": "test-project"}))
    (project_path / "main.cf").write_text(
        "\n".join(
            [
                "import example::slices::fs",
                "import example::slices::fs::unroll",
                "import example::slices::simple",
                "import example::slices::recursive",
            ]
        )
    )

    def git_ops(*args: str, expect_failure: bool = False) -> str:
        result = subprocess.run(
            ["git-ops", "project", *args],
            cwd=project_path,
            env={**os.environ},
            text=True,
            capture_output=True,
        )
        if expect_failure:
            assert result.returncode != 0, result.stdout + result.stderr
        else:
            assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    # No slices yet
    assert json.loads(git_ops("slice", "list", "--format", "json")) == []

    # Scaffold a new fs slice, the created file contains a placeholder for
    # each required property of the store schema.  The created path, printed
    # to stdout, is relative to the directory the command is invoked from.
    created = git_ops("slice", "create", "--store", "fs", "--name", "test-folder")
    fs_source = project_path / "files" / "fs" / "test-folder.json"
    assert project_path / created.strip() == fs_source
    assert json.loads(fs_source.read_text()) == {
        "name": "<REPLACE_THIS>",
        "root": "<REPLACE_THIS>",
    }

    # Refuse to overwrite an existing source slice
    git_ops(
        "slice",
        "create",
        "--store",
        "fs",
        "--name",
        "test-folder",
        expect_failure=True,
    )

    # Refuse to create a slice in an unknown store
    git_ops(
        "slice", "create", "--store", "unknown", "--name", "test", expect_failure=True
    )

    # Scaffold a yaml slice, with a mandatory embedded relation
    created = git_ops(
        "slice",
        "create",
        "--store",
        "recursive",
        "--name",
        "rec",
        "--extension",
        "yaml",
    )
    rec_source = project_path / "files" / "recursive" / "rec.yaml"
    assert project_path / created.strip() == rec_source
    assert yaml.safe_load(rec_source.read_text()) == {
        "name": "<REPLACE_THIS>",
        "embedded_required": {"name": "<REPLACE_THIS>"},
    }
    rec_source.unlink()

    # Fill in the placeholders of the fs slice
    fs_source.write_text(json.dumps({"name": "folder", "root": "/tmp"}))

    # The slice now shows up in the list, with the version it would be
    # assigned during an update compile
    assert json.loads(git_ops("slice", "list", "--format", "json")) == [
        {"name": "test-folder", "store_name": "fs", "version": 1, "deleted": False}
    ]

    # The table output contains the slice details
    table = git_ops("slice", "list")
    assert "Store" in table
    assert "fs" in table
    assert "test-folder" in table

    # Inspect the slice, the output is the fully resolved merged slice
    inspected = json.loads(
        git_ops("slice", "inspect", "--store", "fs", "--name", "test-folder")
    )
    assert inspected["name"] == "test-folder"
    assert inspected["store_name"] == "fs"
    assert inspected["version"] == 1
    assert inspected["deleted"] is False
    assert inspected["attributes"]["operation"] == "create"
    assert inspected["attributes"]["path"] == "."
    assert inspected["attributes"]["version"] == 1
    assert inspected["attributes"]["slice_store"] == "fs"
    assert inspected["attributes"]["slice_name"] == "test-folder"
    assert inspected["attributes"]["name"] == "folder"
    assert inspected["attributes"]["root"] == "/tmp"
    assert inspected["attributes"]["content"] == []

    # Inspecting a slice that doesn't exist fails
    git_ops(
        "slice", "inspect", "--store", "fs", "--name", "missing", expect_failure=True
    )

    # Sync the slice to the active store, then delete its source file
    git_ops("sync")
    fs_source.unlink()

    # The slice is still listed, as a deleted slice with a new version
    assert json.loads(git_ops("slice", "list", "--format", "json")) == [
        {"name": "test-folder", "store_name": "fs", "version": 2, "deleted": True}
    ]

    # An empty source slice which never had any active version is ignored
    empty_source = project_path / "files" / "simple" / "empty.json"
    empty_source.parent.mkdir(parents=True, exist_ok=True)
    empty_source.write_text("{}")
    assert (
        json.loads(git_ops("slice", "list", "--store", "simple", "--format", "json"))
        == []
    )
