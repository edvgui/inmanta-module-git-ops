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

import os
import pathlib
import subprocess


def test_basics() -> None:
    example_path = pathlib.Path(__file__).parent.parent / "docs/example"

    # Test generation of the model
    subprocess.run(
        ["git-ops", "generate"],
        check=True,
        env={"INMANTA_GIT_OPS_MODULE_PATH": str(example_path), **os.environ},
    )

    # List stores
    subprocess.run(
        ["git-ops", "store", "list"],
        check=True,
        env={"INMANTA_GIT_OPS_MODULE_PATH": str(example_path), **os.environ},
    )

    # Generate openapi definitions
    subprocess.run(
        ["git-ops", "store", "schema", "--store", "fs"],
        check=True,
        env={"INMANTA_GIT_OPS_MODULE_PATH": str(example_path), **os.environ},
    )
