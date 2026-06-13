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

import importlib
import sys
import types
from collections.abc import Generator

import pytest

from inmanta.loader import unload_inmanta_plugins


@pytest.fixture(autouse=True)
def restore_sys_modules() -> Generator[None, None, None]:
    """
    These tests reload the plugin modules, which mutates ``sys.modules``
    globally.  Snapshot it and restore the original module objects afterwards so
    that other test modules (which captured their imports at collection time)
    keep seeing the same objects.
    """
    snapshot = dict(sys.modules)
    try:
        yield
    finally:
        sys.modules.clear()
        sys.modules.update(snapshot)
        importlib.invalidate_caches()


def fresh_import(module: str) -> types.ModuleType:
    """
    Unload all inmanta plugin modules and import the given one again, mimicking
    what the inmanta compiler does at the start of a compile: replace the
    sys.modules entries with brand new module objects holding brand new class
    objects.
    """
    unload_inmanta_plugins()
    return importlib.import_module(module)


def test_discriminated_union_survives_plugin_reload() -> None:
    """
    A slice model carrying a forward-referenced discriminated-union field (the
    union is defined after the model, like ``Folder.content``) used to raise a
    spurious ``ValidationError`` the first time it was validated after a compile
    reloaded the plugin modules.

    Pydantic resolves the forward reference lazily, against
    ``sys.modules[model.__module__]``.  After a reload that entry holds a brand
    new ``File`` class, while a long-lived consumer still holds an instance of
    the old ``File``.  The discriminated union then rejects an instance of the
    very class it expects.  Registering a store now resolves all the slice
    models eagerly, binding each to its own classes before any reload.
    """
    # Start from a clean import so the outcome does not depend on whichever
    # model an earlier test happened to validate (the bug is masked once a
    # model's schema has been built before the reload).
    fs = fresh_import("inmanta_plugins.example.slices.fs")

    # A leaf instance built from the freshly imported classes.  ``File`` has no
    # union field, so building it does not resolve ``Folder``'s union: that
    # resolution is what must survive the reload.
    leaf = fs.File(name="a.txt", content="a")
    folder_cls = fs.Folder

    # The compiler reloads the plugins: a brand new module replaces the old one.
    fresh_import("inmanta_plugins.example.slices.fs")

    # Validating the old ``Folder`` for the first time, after the reload, must
    # accept the old ``File`` instance instead of rejecting it.
    folder = folder_cls(name="b", content=[leaf])
    assert folder.content == [leaf]
