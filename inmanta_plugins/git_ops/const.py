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

import pydantic

from inmanta_plugins.git_ops import CompileMode

COMPILE_UPDATE = "update"
COMPILE_SYNC = "sync"
COMPILE_EXPORT = "export"

COMPILE_MODE_ENV_VAR = "INMANTA_GIT_OPS_COMPILE_MODE"
COMPILE_MODE_ADAPTER = pydantic.TypeAdapter(CompileMode)
COMPILE_MODE = COMPILE_MODE_ADAPTER.validate_python(
    os.getenv(COMPILE_MODE_ENV_VAR, COMPILE_EXPORT)
)
