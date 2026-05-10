# GitOps module

[![pypi version](https://img.shields.io/pypi/v/inmanta-module-git-ops.svg)](https://pypi.python.org/pypi/inmanta-module-git-ops/)
[![build status](https://img.shields.io/github/actions/workflow/status/edvgui/inmanta-module-git-ops/continuous-integration.yml)](https://github.com/edvgui/inmanta-module-git-ops/actions)

This package is an integration module that is meant to be used with the inmanta orchestrator: https://docs.inmanta.com

It allows you to easily parametrize a model by defining slices, and then instantiating as many slices as you need to by simply creating json or yaml files in the project repository.  This module aims at enabling its users to manage an infra in a "Git-Ops" fashion.  Key ideas are:
1. Declarative Configuration: The desired state of your infrastructure and applications is described in a declarative format (json/yaml files) within a Git repository. 
2. Version Control: Git serves as the central source of truth, meaning all changes are committed to the repository, providing a complete history of the system's evolution. 
3. Automated Synchronization: The orchestrator continuously monitors the Git repository and pulls in new updates. 
4. Pull Requests for Changes: When you want to make a change, you create a pull request to modify the Git repository. 
5. Deployment & Reconciliation: Once the pull request is approved and merged, the orchestrator automatically pulls the changes and deploys them to the live environment, ensuring the actual system state matches the desired state in Git.

All of this is already natively supported by the orchestrator by modifying the `main.cf` file of a project.  This works but scales poorly and it is not possible to track deleted items, this modules aims at addressing these limitations.

More details about the design in the [docs](docs/) folder.

## Packaged modules

The `inmanta-module-git-ops` python package ships three top-level modules:

- `inmanta_plugins.git_ops`: the inmanta module itself, containing the plugins, slice/store
  primitives and processors used by the model.  This is the public API to import from other
  inmanta modules building on top of git_ops.
- `pytest_inmanta_git_ops`: a pytest plugin exposing the `git_ops_project` fixture and the
  `GitOpsProject` helper class to write tests for modules using git_ops.  This is the public
  API to import from the test suite of other inmanta modules.
- `inmanta_git_ops`: holds code that must live outside of `inmanta_plugins` (constants, the
  `git-ops` CLI, the project generator).  The `inmanta_plugins` namespace can be reloaded
  by various code paths (notably the `clean_reset` fixture from `inmanta-core`), so anything
  that needs stable module-level state (e.g. constants used as monkeypatch targets) is
  extracted here.  This module is **not** meant to be imported from other inmanta modules.

## Cli

This module also provides a cli interface, to facilitate the creation of a module based on git_ops and the management of a project using git_ops.

If the module is installed in your venv, just run the `git-ops` command.

```console
$ git-ops --help
Usage: git-ops [OPTIONS] COMMAND [ARGS]...

  Inmanta module git_ops CLI tool.

Options:
  --log-level [DEBUG|INFO|WARNING|ERROR]
  --help                          Show this message and exit.

Commands:
  module   Commands to manage the module containing slice definitions.
  project  Commands to manage the current Inmanta project.
```


## Testing modules built on git_ops

The `pytest_inmanta_git_ops` plugin provides a `git_ops_project` fixture that wraps the
`pytest-inmanta` `project` fixture and lets you drive update/sync/export/prune compiles
on a model, write/remove slices, and assert on the resulting instances.

```python
from inmanta_plugins.example.slices import fs
from pytest_inmanta_git_ops.project import GitOpsProject


def test_fs(git_ops_project: GitOpsProject) -> None:
    git_ops_project.load_stores("import example::slices::fs::unroll")

    slice1 = git_ops_project.test_slice(
        fs.RootFolder(root="/tmp/", name="test"),
        store_name=fs.STORE.name,
    )

    # Write the slice to disk and trigger an update + sync compile
    assert git_ops_project.write_slice(slice1).version == 1
    assert len(git_ops_project.get_instance(slice1).directories) == 0

    # Mutate the slice, write again, and check the new version
    slice1.slice.directories = [fs.Folder(name="a"), fs.Folder(name="b")]
    assert git_ops_project.write_slice(slice1).version == 2

    # Remove the slice
    git_ops_project.remove_slice(slice1)
    git_ops_project.prune()
```

A more complete example lives in [docs/example](docs/example/), including the matching
slice definitions and the full test suite under
[docs/example/tests](docs/example/tests/).

## Running tests

1. Set up a new virtual environment, then install the module in it. The first line assumes you have ``virtualenvwrapper``
installed. If you don't, you can replace it with `python3 -m venv .env && source .env/bin/activate`.

```bash
mkvirtualenv inmanta-test -p python3 -a .
pip install -e . -c requirements.txt -r requirements.dev.txt
```

2. Run tests

```bash
pytest tests
```
