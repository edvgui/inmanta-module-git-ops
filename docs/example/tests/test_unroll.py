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

import pytest
from inmanta_plugins.example.slices import fs, recursive, simple

from inmanta_plugins.git_ops import const
from pytest_inmanta_git_ops.project import GitOpsProject


def test_fs(git_ops_project: GitOpsProject) -> None:
    git_ops_project.load_stores("import example::slices::fs::unroll")

    assert git_ops_project.stores is not None
    assert fs.STORE in git_ops_project.stores.values()

    # Create a first slice
    slice1 = git_ops_project.test_slice(
        fs.RootFolder(
            root="/tmp/",
            name="test",
        ),
        store_name=fs.STORE.name,
    )
    assert git_ops_project.write_slice(slice1).version == 1
    assert len(slice1.get_versions()) == 1
    assert len(git_ops_project.get_instance(slice1).directories) == 0

    # Empty update on the slice, we should get the same version
    assert git_ops_project.write_slice(slice1).version == 1
    assert len(slice1.get_versions()) == 1

    # Add some folder
    slice1.slice.directories = [
        fs.Folder(name="a"),
        fs.Folder(name="b"),
        fs.Folder(name="c"),
    ]
    assert git_ops_project.write_slice(slice1).version == 2
    assert len(slice1.get_versions()) == 2
    assert len(git_ops_project.get_instance(slice1).directories) == 3

    # Prune version after update
    git_ops_project.prune()
    assert len(slice1.get_versions()) == 1

    # Remove a folder
    slice1.slice.directories = [
        fs.Folder(name="a"),
        fs.Folder(name="b"),
    ]
    assert git_ops_project.write_slice(slice1).version == 3
    assert len(slice1.get_versions()) == 2
    assert len(git_ops_project.get_instance(slice1).directories) == 3
    assert (
        next(
            dir
            for dir in git_ops_project.get_instance(slice1).directories
            if dir.operation == const.SLICE_DELETE
        ).name
        == "c"
    )

    # Prune version after update
    git_ops_project.prune()
    assert len(slice1.get_versions()) == 1
    git_ops_project.export()
    assert len(git_ops_project.get_instance(slice1).directories) == 2

    # Delete slice
    assert git_ops_project.remove_slice(slice1).version == 4
    assert git_ops_project.remove_slice(slice1).emit_slice(fs.STORE.name).deleted
    assert len(git_ops_project.get_instance(slice1).directories) == 2

    # Prune after delete
    git_ops_project.prune()
    assert len(slice1.get_versions()) == 0

    with pytest.raises(LookupError):
        git_ops_project.get_instance(slice1)


def test_recursive(git_ops_project: GitOpsProject) -> None:
    git_ops_project.load_stores("import example::slices::recursive")

    assert git_ops_project.stores is not None
    assert recursive.STORE in git_ops_project.stores.values()


def test_simple(git_ops_project: GitOpsProject) -> None:
    git_ops_project.load_stores("import example::slices::simple")

    assert git_ops_project.stores is not None
    assert simple.STORE in git_ops_project.stores.values()
