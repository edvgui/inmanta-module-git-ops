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
import typing

import pydantic

type CompileMode = typing.Literal[
    "update",
    "sync",
    "export",
    "prune",
    "slice-create",
    "slice-list",
    "slice-inspect",
]


COMPILE_UPDATE = "update"
COMPILE_SYNC = "sync"
COMPILE_EXPORT = "export"
COMPILE_PRUNE = "prune"
COMPILE_EMPTY = "empty"
COMPILE_SLICE_CREATE = "slice-create"
COMPILE_SLICE_LIST = "slice-list"
COMPILE_SLICE_INSPECT = "slice-inspect"

# The compile modes triggered by the `git-ops project slice` commands.  During
# these compiles, no slice is emitted in the model, the command logic is
# executed in a finalizer instead.
COMPILE_SLICE_COMMANDS = [
    COMPILE_SLICE_CREATE,
    COMPILE_SLICE_LIST,
    COMPILE_SLICE_INSPECT,
]

COMPILE_MODE_ENV_VAR = "INMANTA_GIT_OPS_COMPILE_MODE"
COMPILE_MODE_ADAPTER = pydantic.TypeAdapter(CompileMode)
COMPILE_MODE = COMPILE_MODE_ADAPTER.validate_python(
    os.getenv(COMPILE_MODE_ENV_VAR, COMPILE_EXPORT)
)

# Options for the slice command compiles, passed to the compile subprocess
# by the cli, the same way the compile mode is.
SLICE_STORE_ENV_VAR = "INMANTA_GIT_OPS_SLICE_STORE"
SLICE_STORE: str | None = os.getenv(SLICE_STORE_ENV_VAR)

SLICE_NAME_ENV_VAR = "INMANTA_GIT_OPS_SLICE_NAME"
SLICE_NAME: str | None = os.getenv(SLICE_NAME_ENV_VAR)

SLICE_EXTENSION_ENV_VAR = "INMANTA_GIT_OPS_SLICE_EXTENSION"
SLICE_EXTENSION: str = os.getenv(SLICE_EXTENSION_ENV_VAR, "json")

# File in which the result of a slice command should be written by the
# finalizer executing it, so that the cli process can read it back.
OUTPUT_FILE_ENV_VAR = "INMANTA_GIT_OPS_OUTPUT_FILE"
OUTPUT_FILE: str | None = os.getenv(OUTPUT_FILE_ENV_VAR)

SLICE_CREATE = "create"
SLICE_UPDATE = "update"
SLICE_DELETE = "delete"

# Placeholder used for all the required property values of a newly scaffolded
# slice, which the user must replace with real values.
SLICE_PLACEHOLDER = "<REPLACE_THIS>"
