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

import json
import pathlib

import pytest
import yaml
from inmanta_plugins.example.slices.recursive import EmbeddedSlice, Slice
from inmanta_plugins.example.slices.simple import Slice as SimpleSlice
from pytest_inmanta.plugin import Project

from inmanta.ast import ExternalException
from inmanta_plugins.git_ops import const
from inmanta_plugins.git_ops.store import SliceStore


def test_migrations(
    project: Project, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Define a basic store
    store = SliceStore(
        name="test_migrations",
        folder="file://" + str(tmp_path / "test"),
        schema=Slice,
    )

    model = """
        import git_ops
        git_ops::unroll_slices("test_migrations")
    """

    # Basic compile should always be fine
    project.compile(model)

    # Add some one slice to the folder
    s1_obj = Slice(
        name="a",
        embedded_required=EmbeddedSlice(
            name="aa",
        ),
    )
    s1 = store.source_path / "s1.yaml"
    s1.parent.mkdir(parents=True, exist_ok=True)
    s1.write_text(yaml.safe_dump(s1_obj.model_dump(mode="json")))
    s1_v1 = store.active_path / "s1@v1.json"
    s1_v2 = store.active_path / "s1@v2.json"

    # Compile with one slice
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_UPDATE)
        project.compile(model, no_dedent=False)
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_SYNC)
        project.compile(model, no_dedent=False)

    assert s1_v1.exists()
    assert not s1_v2.exists()
    assert (
        yaml.safe_load(s1.read_text())
        == json.loads(s1_v1.read_text())
        == {
            "name": "a",
            "description": None,
            "embedded_optional": None,
            "embedded_required": {
                "name": "aa",
                "description": None,
                "recursive_slice": [],
                "unique_id": None,
            },
            "embedded_sequence": [],
            "unique_id": None,
        }
    )

    # Now add a migration that adds a new field, and try to compile again, which
    # should fail because the active slice is not up to date with the latest schema
    @store.migration("001_new_slice_format")
    def new_slice_format(attrs: dict) -> dict:
        assert (
            "some_number" not in attrs
        ), "some_number should not be in the attributes of the old slice format"
        return {
            "name": attrs["name"],
            "description": attrs.get("description"),
            "unique_id": attrs.get("unique_id"),
            "some_number": 0.0,
            "some_flag": False,
            "some_list": [],
            "some_dict": {},
        }

    assert len(store.pending_migrations()) == 1

    # Update the store schema to the new slice format, which should trigger the migration during the next compile
    store.schema = SimpleSlice

    # Update compile should apply all pending migrations
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_UPDATE)
        project.compile(model, no_dedent=False)

        # Second compile should not apply the migration again, because it is already applied, and should not change anything
        project.compile(model, no_dedent=False)

    assert len(store.pending_migrations()) == 0

    assert s1_v1.exists()
    assert not s1_v2.exists()
    assert (
        yaml.safe_load(s1.read_text())
        == json.loads(s1_v1.read_text())
        == {
            "name": "a",
            "description": None,
            "unique_id": None,
            "some_number": 0.0,
            "some_flag": False,
            "some_list": [],
            "some_dict": {},
        }
    )

    # Do another migration going back to the previous format
    @store.migration("002_old_slice_format")
    def old_slice_format(attrs: dict) -> dict:
        assert (
            "some_number" in attrs
        ), "some_number should be in the attributes of the new slice format"
        return {
            "name": attrs["name"],
            "description": attrs.get("description"),
            "unique_id": attrs.get("unique_id"),
            "embedded_required": {
                "name": attrs["name"] + "a",
                "description": None,
                "recursive_slice": [],
                "unique_id": None,
            },
            "embedded_optional": None,
            "embedded_sequence": [],
        }

    assert len(store.pending_migrations()) == 1

    # Update the store schema to the old slice format, which should trigger the migration during the next compile
    store.schema = Slice

    # Verify that any non-update compile mode does not apply the migration, and that the active slice is still in the new format
    for mode in [const.COMPILE_SYNC, const.COMPILE_EXPORT]:
        with pytest.raises(ExternalException) as exc:
            with monkeypatch.context() as ctx:
                ctx.setattr(const, "COMPILE_MODE", mode)
                project.compile(model, no_dedent=False)

        cause = exc.value.__cause__
        assert cause is not None
        assert "Migrations can only be applied during an update compile" in str(cause)
        assert "002_old_slice_format" in str(cause)
        assert store.name in str(cause)
        assert "001_new_slice_format" not in str(cause)
        assert len(store.pending_migrations()) == 1

    # Verify that prune still works even if there are some pending migrations
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_PRUNE)
        project.compile(model, no_dedent=False)

    # Compile with one slice
    with monkeypatch.context() as ctx:
        ctx.setattr(const, "COMPILE_MODE", const.COMPILE_UPDATE)
        project.compile(model, no_dedent=False)

        # Second compile should not apply the migration again, because it is already applied, and should not change anything
        project.compile(model, no_dedent=False)

    assert s1_v1.exists()
    assert not s1_v2.exists()
    assert (
        yaml.safe_load(s1.read_text())
        == json.loads(s1_v1.read_text())
        == {
            "name": "a",
            "description": None,
            "embedded_optional": None,
            "embedded_required": {
                "name": "aa",
                "description": None,
                "recursive_slice": [],
                "unique_id": None,
            },
            "embedded_sequence": [],
            "unique_id": None,
        }
    )


def test_migrations_initial_compile(project: Project, tmp_path: pathlib.Path) -> None:
    """
    A brand-new store (active folder does not exist yet) with registered migrations
    should treat those migrations as already applied: there are no slices to migrate.
    Without this, a non-update compile mode would fail because pending_migrations()
    would report every registered migration as pending.
    """
    store = SliceStore(
        name="test_migrations_initial_compile",
        folder="file://" + str(tmp_path / "test"),
        schema=Slice,
    )

    @store.migration("001_noop")
    def noop(attrs: dict) -> dict:
        return attrs

    assert not store.active_path.exists()
    assert not store.migration_state_path.exists()

    model = """
        import git_ops
        git_ops::unroll_slices("test_migrations_initial_compile")
    """

    # Default compile mode (empty) — must not raise even though a migration is registered
    project.compile(model)

    assert store.active_path.exists()
    assert store.migration_state_path.exists()
    assert json.loads(store.migration_state_path.read_text())["applied"] == list(
        store.migrations.keys()
    )
    assert store.pending_migrations() == []
