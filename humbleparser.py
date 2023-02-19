"""
No warranty, express or implied! But do whatever you want with this.

Originally by `https://github.com/decorator-factory`, circa 2023
"""


from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
import textwrap
from typing import Any, TypeVar, Union
import typing

__all__ = (
    "PathKey",
    "Parser",
    "ParseError",
    "apply_prefix",
    "apply_note",
    "ErrorValue",
    "Verbose",
    "Expectation",
    "MultipleErrors",
    "AtIndex",
    "AtKey",
    "Note",
    "is_type",
    "is_described_type",
    "is_int",
    "is_str",
    "is_list",
    "is_list_of",
    "is_dict",
    "is_dict_of",
    "is_map",
    "has_field",
    "is_any_of",
    "is_any_of_described",
    "is_variant",
    "dump_error_value_human",
    "dump_error_value_nested",
)


_T = TypeVar("_T")
_U = TypeVar("_U")
_K = TypeVar("_K", bound=Union[int, str])


PathKey = int | str
Parser = Callable[[object], _T]


@dataclass(frozen=True)
class Verbose:
    message: str


@dataclass(frozen=True)
class Expectation:
    expected: str
    actual: str


@dataclass(frozen=True)
class MultipleErrors:
    errors: tuple[ErrorValue, ...]

    def __post_init__(self) -> None:
        if len(self.errors) < 2:
            raise RuntimeError("Expected at least two errors for `MultipleErrors`")


@dataclass(frozen=True)
class AtIndex:
    index: int
    error: ErrorValue


@dataclass(frozen=True)
class AtKey:
    key: str
    error: ErrorValue


@dataclass
class Note:
    note: str
    original: ErrorValue


ErrorValue = Union[
    Verbose,
    Expectation,
    MultipleErrors,
    AtIndex,
    AtKey,
    Note,
]


class ParseError(Exception):
    def __init__(self, error: ErrorValue, /) -> None:
        self._error = error
        super().__init__(error)

    def __str__(self):
        return dump_error_value_human(self._error)

    @property
    def error(self) -> ErrorValue:
        return self._error


def dump_error_value_human(e: ErrorValue, /) -> str:
    if isinstance(e, Verbose):
        return e.message
    elif isinstance(e, AtIndex):
        return f"at index {e.index!r}: {dump_error_value_human(e.error)}"
    elif isinstance(e, AtKey):
        return f"at key {e.key!r}: {dump_error_value_human(e.error)}"
    elif isinstance(e, Expectation):
        return f"expected {e.expected}, got {e.actual}"
    elif isinstance(e, MultipleErrors):
        points = ("- " + dump_error_value_human(sub_e) for sub_e in e.errors)
        points = [textwrap.indent(point, "    ") for point in points]
        return "all possibilities failed:\n" + "\n".join(points)
    elif isinstance(e, Note):
        return f"({e.note}) {dump_error_value_human(e.original)}"
    else:
        typing.assert_never(e)


def dump_error_value_nested(e: ErrorValue, /) -> object:
    if isinstance(e, Verbose):
        return e.message
    elif isinstance(e, AtIndex):
        return {"at_index": e.index, "error": dump_error_value_nested(e.error)}
    elif isinstance(e, AtKey):
        return {"at_key": e.key, "error": dump_error_value_nested(e.error)}
    elif isinstance(e, Expectation):
        return {"expected": e.expected, "actual": e.actual}
    elif isinstance(e, MultipleErrors):
        return {"multiple_errors": list(map(dump_error_value_nested, e.errors))}
    elif isinstance(e, Note):
        return {"note": e.note, "error": dump_error_value_nested(e.original)}
    else:
        typing.assert_never(e)


@contextlib.contextmanager
def apply_prefix(*prefix: PathKey) -> Iterator[None]:
    try:
        yield
    except ParseError as exc:
        error = exc.error
        for key in prefix:
            if isinstance(key, int):
                error = AtIndex(key, error)
            else:
                error = AtKey(key, error)

        raise ParseError(error) from exc


@contextlib.contextmanager
def apply_note(note: str) -> Iterator[None]:
    try:
        yield
    except ParseError as exc:
        raise ParseError(Note(note, exc.error)) from exc


def is_described_type(t: type[_T], description: str) -> Parser[_T]:
    def _is_type(source: object) -> _T:
        if not isinstance(source, t):
            raise ParseError(
                Expectation(expected=description, actual=str(type(source)))
            )
        return source

    return _is_type


def is_type(t: type[_T]) -> Parser[_T]:
    return is_described_type(t, str(t))


def is_int(source: object) -> int:
    if not isinstance(source, int) or isinstance(source, bool):
        raise ParseError(Expectation(expected="integer", actual=str(type(source))))
    return source


is_str: Parser[str] = is_described_type(str, "a string")

is_list: Parser[list[Any]] = is_described_type(list, "a list")

is_dict: Parser[dict[Any, Any]] = is_described_type(dict, "a dictionary")


def is_list_of(is_item: Parser[_T]) -> Parser[list[_T]]:
    def _is_list_of(source: object) -> list[_T]:
        raw_list = is_list(source)
        result: list[_T] = []
        for i, raw_item in enumerate(raw_list):
            with apply_prefix(i):
                parsed_item = is_item(raw_item)
            result.append(parsed_item)
        return result

    return _is_list_of


def is_dict_of(is_key: Parser[_K], is_value: Parser[_T]) -> Parser[dict[_K, _T]]:
    def _is_dict_of(source: object) -> dict[_K, _T]:
        raw_dict = is_dict(source)
        result: dict[_K, _T] = {}
        for raw_key, raw_item in raw_dict.items():
            parsed_key = is_key(raw_key)
            with apply_prefix(parsed_key):
                parsed_value = is_value(raw_item)
            result[parsed_key] = parsed_value
        return result

    return _is_dict_of


def is_map(is_value: Parser[_T]) -> Parser[dict[str, _T]]:
    return is_dict_of(is_str, is_value)


def has_field(name: str, is_value: Parser[_T]) -> Parser[_T]:
    def _has_field(source: object) -> _T:
        raw_dict = is_dict(source)
        with apply_prefix(name):
            if name not in raw_dict:
                raise ParseError(Verbose(f"Key {name!r} not found"))

            return is_value(raw_dict[name])

    return _has_field


def is_any_of(first: Parser[_T], /, *rest: Parser[_T]) -> Parser[_T]:
    if not rest:
        return first

    options = (first, *rest)

    def _is_any_of(source: object) -> _T:
        errors: list[ErrorValue] = []
        for option in options:
            try:
                return option(source)
            except ParseError as exc:
                errors.append(exc.error)

        raise ParseError(MultipleErrors(tuple(errors)))

    return _is_any_of


def is_any_of_described(*options: tuple[str, Parser[_T]]) -> Parser[_T]:
    if len(options) < 2:
        raise RuntimeError("Expected at least 2 options")

    def _is_any_of_described(source: object) -> _T:
        errors: list[ErrorValue] = []
        for label, option in options:
            try:
                with apply_note(label):
                    return option(source)
            except ParseError as exc:
                errors.append(exc.error)

        raise ParseError(MultipleErrors(tuple(errors)))

    return _is_any_of_described


def is_variant(
    is_tag: Parser[_U],
    variants: Mapping[_U, Parser[_T]],
) -> Parser[_T]:
    expected_tags = " or ".join(map(repr, variants))

    def _is_variant(source: object) -> _T:
        with apply_note("Unknown variant"):
            tag = is_tag(source)
            if tag not in variants:
                raise ParseError(Expectation(expected_tags, repr(tag)))

        variant = variants[tag]

        with apply_note(str(tag)):
            return variant(source)

    return _is_variant
