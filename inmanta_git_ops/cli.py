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
import json
import logging
import os
import pathlib
import subprocess
import sys
import tempfile
import typing
from collections.abc import Mapping, Sequence

import click
import texttable

from inmanta.module import ModuleV2, Project
from inmanta_git_ops import const
from inmanta_plugins.git_ops.store import SLICE_STORE_REGISTRY

LOGGER = logging.getLogger(__name__)


@click.group()
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
)
def cli(log_level: str) -> None:
    """
    Inmanta module git_ops CLI tool.
    """
    logging.basicConfig(level=log_level)


MODULE: ModuleV2 | None = None


@cli.group("module")
@click.option(
    "--module-path",
    type=click.Path(exists=True, file_okay=False),
    help="Path to the module to operate on.",
    envvar="INMANTA_GIT_OPS_MODULE_PATH",
    default=".",
    show_default=True,
    show_envvar=True,
)
def module(
    module_path: str,
) -> None:
    """
    Commands to manage the module containing slice definitions.
    """

    global MODULE
    MODULE = ModuleV2.from_path(module_path)
    if MODULE is None:
        raise click.BadParameter(f"Could not load module from path {module_path}")

    # The generator needs the module to be marked as editable
    MODULE._is_editable_install = True
    LOGGER.debug("Found module %s at path %s", MODULE.name, MODULE._path)

    for file in pathlib.Path(MODULE.get_plugin_dir()).rglob("*.py"):
        # For each python file in the module, try to import it to load the slice definitions
        relative_path = file.relative_to(MODULE.get_plugin_dir())
        module_name = f"inmanta_plugins.{MODULE.name}." + relative_path.with_suffix(
            ""
        ).as_posix().replace("/", ".")
        LOGGER.debug(f"Importing module {module_name} from {file}")
        importlib.import_module(module_name)


@module.command("generate")
@click.option(
    "--explicit-parent-relations",
    is_flag=True,
    help="Whether to generate explicit parent relations in the model.",
    envvar="INMANTA_GIT_OPS_EXPLICIT_PARENT_RELATIONS",
    default=False,
    show_envvar=True,
)
def generate(explicit_parent_relations: bool) -> None:
    """
    Generate the model for the slices defined in the input module.
    """
    from inmanta_git_ops import generator

    if explicit_parent_relations:
        generator.EXPLICIT_PARENT_RELATIONS = True

    assert MODULE is not None
    builder = generator.get_module_builder(MODULE.name)

    # Collect the schema for all registered slice stores and generate the corresponding entities
    slices = [store.schema.entity_schema() for store in SLICE_STORE_REGISTRY.values()]
    [generator.get_entity(s, slice_root=True) for s in slices]

    builder.upgrade_existing_module(MODULE, fix_linting=False)


@module.group("store")
def store() -> None:
    """
    Commands to manage slice stores.
    """
    pass


@store.command("list")
@click.option(
    "--format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
def list_stores(format: str) -> None:
    """
    List all registered slice stores.
    """
    if format == "json":
        stores = [
            {
                "name": store.name,
                "path": store._folder,
                "description": (store.schema.__doc__ or "").strip(),
                "python_type": f"{store.schema.__module__}.{store.schema.__name__}",
            }
            for store in SLICE_STORE_REGISTRY.values()
        ]
        click.echo(json.dumps(stores, indent=2))
        return

    elif format == "table":
        table = texttable.Texttable()
        table.header(["Name", "Path", "Description"])

        for store in SLICE_STORE_REGISTRY.values():
            description = store.schema.__doc__ or ""
            description = description.strip().split("\n")[
                0
            ]  # Get the first line of the docstring
            table.add_row([store.name, store._folder, description])

        click.echo(table.draw())

    else:
        raise click.BadParameter(f"Unsupported format {format}")


@store.command("schema")
@click.option(
    "--store",
    type=str,
    required=True,
    help="The name of the store to get the schema for.",
)
def schema(store: str) -> None:
    """
    Print the JSON schema for the given store.
    """
    if store not in SLICE_STORE_REGISTRY:
        raise click.BadParameter(f"Store {store} is not registered")

    schema = SLICE_STORE_REGISTRY[store].schema
    click.echo(json.dumps(schema.model_json_schema(), indent=2))


PROJECT: Project | None = None
INMANTA_ARGS: list[str] = []


@cli.group("project")
@click.option(
    "--inmanta-arg",
    multiple=True,
    help="Additional arguments to pass to the inmanta command.",
)
def project(inmanta_arg: list[str]) -> None:
    """
    Commands to manage the current Inmanta project.
    """
    global PROJECT
    PROJECT = Project.get()

    INMANTA_ARGS.extend(inmanta_arg)


def run_compile(
    inmanta_compile_arg: Sequence[str],
    *,
    compile_mode: str,
    env: Mapping[str, str] | None = None,
    stdout: typing.IO | None = None,
) -> None:
    """
    Run a compile on the current project, in a subprocess, with the given
    compile mode.

    :param inmanta_compile_arg: Additional arguments to pass to the inmanta
        compile command.
    :param compile_mode: The compile mode the compile should run in.
    :param env: Additional environment variables to pass to the compile.
    :param stdout: Where to redirect the standard output of the compile.
    """
    subprocess.run(
        [
            sys.executable,
            "-m",
            "inmanta.app",
            *INMANTA_ARGS,
            "compile",
            *inmanta_compile_arg,
        ],
        check=True,
        env={**os.environ, const.COMPILE_MODE_ENV_VAR: compile_mode, **(env or {})},
        stdout=stdout,
    )


# Environment variables, defined by inmanta-core, with which the user can
# set the logging configuration of the compiler.
COMPILER_LOGGING_CONTENT_ENV_VAR = "INMANTA_LOGGING_COMPILER_CONTENT"
COMPILER_LOGGING_ENV_VARS = [
    "INMANTA_LOGGING_COMPILER",
    COMPILER_LOGGING_CONTENT_ENV_VAR,
    "INMANTA_LOGGING_COMPILER_TMPL",
    "INMANTA_CONFIG_LOGGING_CONFIG",
    "INMANTA_CONFIG_LOGGING_CONFIG_CONTENT",
    "INMANTA_CONFIG_LOGGING_CONFIG_TMPL",
]

# Logging configuration for the slice command compiles: send all the compiler
# logs to stderr, so that the compiler doesn't log anything on stdout.  The
# inmanta.logging logger is restricted to errors because it warns about the
# default cli logging options it ignores when a logging config is provided.
SLICE_COMPILE_LOGGING_CONFIG = """
version: 1
disable_existing_loggers: false
formatters:
  console:
    format: "%(name)-25s%(levelname)-8s%(message)s"
handlers:
  console:
    class: logging.StreamHandler
    formatter: console
    level: WARNING
    stream: ext://sys.stderr
loggers:
  inmanta.logging:
    level: ERROR
root:
  handlers: [console]
  level: WARNING
"""


def run_slice_command_compile(
    inmanta_compile_arg: Sequence[str],
    *,
    compile_mode: str,
    env: Mapping[str, str],
) -> object:
    """
    Run a slice command compile on the current project.  The compiler is
    configured to log to stderr, and any remaining output on stdout is
    redirected to stderr too.  The result of the command, written to the
    output file by the corresponding finalizer, is read back and returned.

    :param inmanta_compile_arg: Additional arguments to pass to the inmanta
        compile command.
    :param compile_mode: The compile mode the compile should run in.
    :param env: Additional environment variables to pass to the compile.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_file = pathlib.Path(tmp_dir) / "output.json"
        compile_env = {**env, const.OUTPUT_FILE_ENV_VAR: str(output_file)}
        if not any(var in os.environ for var in COMPILER_LOGGING_ENV_VARS):
            # The user didn't configure the compiler logging, make sure the
            # compiler doesn't log anything on stdout
            compile_env[COMPILER_LOGGING_CONTENT_ENV_VAR] = SLICE_COMPILE_LOGGING_CONFIG
        try:
            run_compile(
                inmanta_compile_arg,
                compile_mode=compile_mode,
                env=compile_env,
                stdout=sys.stderr,
            )
        except subprocess.CalledProcessError as e:
            raise click.ClickException(
                f"The compile failed (see logs above): {e}"
            ) from e

        if not output_file.exists():
            raise click.ClickException(
                "The compile didn't emit any result for the slice command.  "
                "Make sure the project model imports the git_ops module."
            )

        return json.loads(output_file.read_text())


@project.command("update")
@click.option(
    "--inmanta-compile-arg",
    multiple=True,
    help="Additional arguments to pass to the inmanta compile command.",
)
def update(inmanta_compile_arg: list[str]) -> None:
    """
    Update the source slices.

    Read each source slice, and update their content if processors need to resolve some values.
    Verify that the input data is correct, don't export any resource to the orchestrator.
    """
    run_compile(inmanta_compile_arg, compile_mode=const.COMPILE_UPDATE)


@project.command("sync")
@click.option(
    "--inmanta-compile-arg",
    multiple=True,
    help="Additional arguments to pass to the inmanta compile command.",
)
def sync(inmanta_compile_arg: list[str]) -> None:
    """
    Commit the source slices.

    Read each source slice, and if they have a more recent version or are deleted, update the slice store accordingly
    by emitting a newer version of the slice or marking it as deleted.  This will make sure the slice store is in sync
    with the source slices, and that the orchestrator will receive the expected resources when doing the next export.
    """
    run_compile(inmanta_compile_arg, compile_mode=const.COMPILE_SYNC)


@project.command("prune")
@click.option(
    "--inmanta-compile-arg",
    multiple=True,
    help="Additional arguments to pass to the inmanta compile command.",
)
def prune(inmanta_compile_arg: list[str]) -> None:
    """
    Prune the slice store.

    Remove from the slice store all active slices which have a more recent version
    or which are deleted.
    """
    run_compile(inmanta_compile_arg, compile_mode=const.COMPILE_PRUNE)


@project.group("slice")
def slice() -> None:
    """
    Commands to manage individual slices of the current Inmanta project.
    """
    pass


@slice.command("create")
@click.option(
    "--store",
    type=str,
    help="The name of the store in which the slice should be created.",
    envvar=const.SLICE_STORE_ENV_VAR,
    prompt=True,
    show_envvar=True,
)
@click.option(
    "--name",
    type=str,
    help="The name of the slice to create, used as the source file name.",
    envvar=const.SLICE_NAME_ENV_VAR,
    prompt=True,
    show_envvar=True,
)
@click.option(
    "--extension",
    type=click.Choice(["json", "yaml"]),
    default="json",
    help="The format of the created slice file.",
    envvar=const.SLICE_EXTENSION_ENV_VAR,
    show_default=True,
    show_envvar=True,
)
@click.option(
    "--inmanta-compile-arg",
    multiple=True,
    help="Additional arguments to pass to the inmanta compile command.",
)
def create(
    store: str,
    name: str,
    extension: str,
    inmanta_compile_arg: list[str],
) -> None:
    """
    Scaffold a new source slice file for the given store.

    The created file contains all the properties of the store's schema: the
    required ones with a placeholder value that should be replaced by the user,
    the others pre-filled with their default value.  The path of the created
    file is printed to stdout.
    """
    path = run_slice_command_compile(
        inmanta_compile_arg,
        compile_mode=const.COMPILE_SLICE_CREATE,
        env={
            const.SLICE_STORE_ENV_VAR: store,
            const.SLICE_NAME_ENV_VAR: name,
            const.SLICE_EXTENSION_ENV_VAR: extension,
        },
    )
    click.echo(path)


@slice.command("inspect")
@click.option(
    "--store",
    type=str,
    help="The name of the store in which the slice is defined.",
    envvar=const.SLICE_STORE_ENV_VAR,
    prompt=True,
    show_envvar=True,
)
@click.option(
    "--name",
    type=str,
    help="The name of the slice to inspect.",
    envvar=const.SLICE_NAME_ENV_VAR,
    prompt=True,
    show_envvar=True,
)
@click.option(
    "--inmanta-compile-arg",
    multiple=True,
    help="Additional arguments to pass to the inmanta compile command.",
)
def inspect(store: str, name: str, inmanta_compile_arg: list[str]) -> None:
    """
    Dump the fully-resolved view of a single slice as JSON.

    The output matches the view of the slice during an update compile: the merged
    current and previous attributes, with operation/path markers, and the version
    the slice would be assigned.
    """
    result = run_slice_command_compile(
        inmanta_compile_arg,
        compile_mode=const.COMPILE_SLICE_INSPECT,
        env={
            const.SLICE_STORE_ENV_VAR: store,
            const.SLICE_NAME_ENV_VAR: name,
        },
    )
    click.echo(json.dumps(result, indent=2))


@slice.command("list")
@click.option(
    "--store",
    type=str,
    default=None,
    help="Only list the slices of the store with this name.",
    envvar=const.SLICE_STORE_ENV_VAR,
    show_envvar=True,
)
@click.option(
    "--format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.option(
    "--inmanta-compile-arg",
    multiple=True,
    help="Additional arguments to pass to the inmanta compile command.",
)
def list_slices(
    store: str | None,
    format: str,
    inmanta_compile_arg: list[str],
) -> None:
    """
    List the slices of the current project, optionally filtered by store.

    Slices present in either the source folder or the active store are listed,
    with the version they would be assigned during an update compile.
    """
    slices = run_slice_command_compile(
        inmanta_compile_arg,
        compile_mode=const.COMPILE_SLICE_LIST,
        env={const.SLICE_STORE_ENV_VAR: store} if store is not None else {},
    )

    if format == "json":
        click.echo(json.dumps(slices, indent=2))
        return

    elif format == "table":
        table = texttable.Texttable()
        table.header(["Store", "Name", "Version", "Deleted"])

        for s in slices:
            table.add_row([s["store_name"], s["name"], s["version"], s["deleted"]])

        click.echo(table.draw())

    else:
        raise click.BadParameter(f"Unsupported format {format}")


if __name__ == "__main__":
    cli()
