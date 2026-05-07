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


from pytest_inmanta_git_ops.project import GitOpsProject
from inmanta_plugins.example.slices import fs, recursive, simple


def test_fs(git_ops_project: GitOpsProject) -> None:
    git_ops_project.load_stores("import example::slices::fs::unroll")

    assert git_ops_project.stores is not None
    assert fs.STORE in git_ops_project.stores.values()

    # Create a first slice
    slice1 = fs.RootFolder(
        root="/tmp/",
        name="test",
    )
    assert git_ops_project.write_slice(slice1).version == 1

    # Empty update on the slice, we should get the same version
    assert git_ops_project.write_slice(slice1).version == 1

    # Add a folder
    slice1.directories = [
        fs.Folder(name="a"),
        fs.Folder(name="b"),
        fs.Folder(name="c"),
    ]
    assert git_ops_project.write_slice(slice1).version == 2


def test_recursive(git_ops_project: GitOpsProject) -> None:
    git_ops_project.load_stores("import example::slices::recursive")

    assert git_ops_project.stores is not None
    assert recursive.STORE in git_ops_project.stores.values()


def test_simple(git_ops_project: GitOpsProject) -> None:
    git_ops_project.load_stores("import example::slices::simple")

    assert git_ops_project.stores is not None
    assert simple.STORE in git_ops_project.stores.values()
