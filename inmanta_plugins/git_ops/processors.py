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

import itertools
import typing
from collections.abc import Collection, Mapping

from inmanta.plugins import plugin
from inmanta.util import dict_path
from inmanta_plugins.git_ops import Slice, attribute_processor, store


@plugin
def used_values(
    store_name: str,
    wild_path: str,
    *,
    name: str | None = None,
    slice_matching: Mapping[str, object] = {},
) -> typing.Annotated[typing.Callable[[], Collection[object]], object]:
    """
    Find all the used values in the described set of slices at the given
    path.  The set of slice can point to either a single slice if a name
    is provided, or the full set of slices if no name is provided.

    The set of slices can then be further filtered by using the slice_matching
    parameter.  Each key should be a path, and each value a primitive that any
    set to keep should have for the attribute that the path points to.

    :param store_name: The name of the store in which the slices should be
        fetched.
    :param wild_path: The wild dict path, pointing to any of the used values
        we may want to return.
    :param name: The name of a unique slice to consider when looking for used
        values.
    :param slice_matching: A filter that allows to select only a subset of the
        slices of the store.
    """
    path = dict_path.to_wild_path(wild_path)

    # Get all the slices in which we should look for used values
    slices = (
        store.get_store(store_name).get_all_slices()
        if name is None
        else [store.get_store(store_name).get_one_slice(name)]
    )

    matching_paths = {
        path: dict_path.to_path(path) for path, _ in slice_matching.items()
    }

    # Filter out the slices which don't match the filter
    def match_filter(s: Slice) -> bool:
        for raw_path, value in slice_matching.items():
            slice_value = matching_paths[raw_path].get_element(s.attributes)
            if slice_value != value:
                return False

        return True

    # Apply the filter to the collection of slices
    slices = [s for s in slices if match_filter(s)]

    def collect_usage() -> Collection[object]:
        return list(itertools.chain(*[path.get_elements(s.attributes) for s in slices]))

    return collect_usage


@plugin
def join_used_values(
    *used_values: typing.Annotated[typing.Callable[[], Collection[object]], object],
) -> typing.Annotated[typing.Callable[[], Collection[object]], object]:
    """
    Join multiple used values collectors into one.
    """

    def collect_usage() -> Collection[object]:
        return list(itertools.chain(*[u() for u in used_values]))

    return collect_usage


@attribute_processor
def unique_integer(
    store_name: str,
    name: str,
    path: str,
    previous_value: int | None = None,
    *,
    used_integers: typing.Annotated[typing.Callable[[], Collection[int]], object],
    range_start: int = 0,
    range_stop: int = 1000,
    refresh: bool = False,
) -> int:
    """
    Pick a unique integer and return it.  The integer will be known to be unique
    if it is not part of all the used integers.
    """
    if previous_value is not None and not refresh:
        # Stable processor, don't change value on each execution
        return previous_value

    all_used_values = set(used_integers())
    free_values = range(range_start, range_stop)
    for v in free_values:
        if v not in all_used_values:
            return v

    raise LookupError(f"No free value in {free_values}")


@attribute_processor
def simple_value(
    store_name: str,
    name: str,
    path: str,
    previous_value: object | None = None,
    *,
    value: object,
    refresh: bool = False,
) -> object:
    """
    Save the current value inside the slice attributes.
    """
    if previous_value is None or refresh:
        return value
    else:
        return previous_value
