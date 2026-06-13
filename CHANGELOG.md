# Changelog

## v0.5.1 - 2026-06-13

- Fix spurious discriminated-union `ValidationError` on slice models with forward-referenced fields after a compile reloaded the plugin modules.

## v0.5.0 - 2026-06-06

- Add `git-ops project slice` command group to create, list and inspect the slices of a project.
- Address some compiler warnings in plugin annotations

## v0.4.0 - 2026-05-30

- Add support for polymorphism in embedded slice definition

## v0.3.1 - 2026-05-12

- Fix initial compile of a store with registered migrations on a fresh active folder.

## v0.3.0 - 2026-05-10

- Add slice migration support
- Fix usage of git_ops::processors::used_values on optional embedded slices
- Add pytest_inmanta_git_ops testing library, installable using [pytest] extra.
- [BREAKING] Moved inmanta_plugins.git_ops.const to inmanta_git_ops.const to avoid module reloading issues.

## v0.2.0 - 2026-04-21

- Allow to generate schema for slice store by using git-ops-config.yml config file
- Add basic cli

## v0.1.5 - 2026-04-01

- Fix recursive deletion

## v0.1.4 - 2026-01-29

- Prevent processing of attributes of deleted slice elements.
- Raise explicit exception when trying to set a value of an attribute on a deleted slice element.

## v0.1.3 - 2026-01-25

- Fix export compiles containing deleted slices (bad path attribute)

## v0.1.2 - 2025-12-22

- Fix export compiles containing deleted slices

## v0.1.1 - 2025-12-05

- Improve desired state stability:
  - Sort slices by name during unrolling
  - Preserve embedded entities order from slice source
- Fix deletion of embedded entities

## v0.1.0 - 2025-12-03

- Initial functional release

## v0.0.1 - 2025-10-04

- First empty release
