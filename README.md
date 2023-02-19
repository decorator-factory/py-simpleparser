> I do not know with what weapons World War III will be fought, but World War IV will be fought with sticks and stones
>
> &mdash; someone, probably

# py-humbleparser

This is a post-modern Python library for parsing/validating unstructured data, such as JSON returned by an HTTP server or a YAML configuration.

This library stems from my dissatisfaction with the popular existing solutions.

## Installation

1. Make sure you're using Python >= 3.9
2. Copy the `humbleparser.py` file from this repository into your project

## Tutorial

For an introduction, we are going to implement a module that works with a small part of [Telegram's Bot API](https://core.telegram.org/bots/api), namely the [`Update` object](https://core.telegram.org/bots/api#update).

### Our model

First, we need to decide how to model this thing. For our humble bot, we will only need two update types:

- `message`: "New incoming message of any kind - text, photo, sticker, etc."
- `edited_message`: "New version of a message that is known to the bot and was edited"

Would this be a good model?
```py
@dataclass(frozen=True)
class Update:
    update_id: int
    message: Union[Message, None] = None
    edited_message: Union[Message, None] = None
```
I don't think that's going to serve us well. It's going to be hard to work with, because there are
invalid and otherwise awkward states this `Update` can be in.

I would use something like this as our model:
```py
@dataclass(frozen=True)
class NewMessage:
    message: Message

@dataclass(frozen=True)
class MessageEdited:
    message: Message

@dataclass(frozen=True)
class UnsupportedUpdate:
    raw: object

UpdateBody = Union[
    NewMessage,
    MessageEdited,
    UnsupportedUpdate,
]

@dataclass(frozen=True)
class Update:
    update_id: int
    body: UpdateBody
```
This describes our domain pretty well:

- we don't support every possible update (hence `UnsupportedUpdate`)
- there is exactly one "event" in an update

### Parsing a `Message`

For now, we'll have a very simple model for a message, because we only need a few things from it:

```py
from __future__ import annotations
from typing import Union
from datetime import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    message_id: int
    sent_at: datetime
    author: Union[User, Chat]
    text: Union[str, None] = None


@dataclass(frozen=True)
class User:
    user_id: int
    first_name: str
    username: Union[str, None] = None


@dataclass(frozen=True)
class Chat:
    chat_id: int
    title: str
```
And here's how you parse a `Message`:
```py
from humbleparser import (
    is_any_of,
    is_int,
    is_str,
    has_field,
    has_optional_field,
    ParseError,
    Verbose,
)


def is_message(source: object) -> Message:
    return Message(
        message_id=has_field("message_id", is_int)(source),
        sent_at=has_field("date", _is_timestamp)(source),
        author=is_any_of(
            has_field("sender_chat", _is_chat),
            has_field("from", _is_user),
        )(source),
        text=has_optional_field("text", is_str)(source),
    )


def _is_chat(source: object) -> Chat:
    return Chat(
        chat_id=has_field("id", is_int)(source),
        title=is_any_of(has_field("title", is_str))(source),
    )


def _is_user(source: object) -> User:
    return User(
        user_id=has_field("id", is_int)(source),
        first_name=has_field("first_name", is_str)(source),
        username=has_optional_field("username", is_str)(source),
    )


def _is_timestamp(source: object) -> datetime:
    timestamp = is_int(source)
    try:
        return datetime.fromtimestamp(timestamp)
    except (ValueError, OverflowError):
        raise ParseError(Verbose("Timestamp is too big"))
```

Let's try our parser on some example messages.
```
message_from_chat = {
    "message_id": 100,
    "date": 1676769964,
    "sender_chat": {"id": 666, "title": "Some Chat"},
}
print(is_message(message_from_chat))

>>> Message(message_id=100, sent_at=datetime.datetime(2023, 2, 19, 4, 26, 4), author=Chat(chat_id=666, title='Some Chat'), text=None)
```
```
message_from_user = {
    "message_id": 25045,
    "date": 1676769966,
    "from": {"id": 11111, "first_name": "Bob"},
    "text": "Hello there!",
}
print(is_message(message_from_user))

>>> Message(message_id=25045, sent_at=datetime.datetime(2023, 2, 19, 4, 26, 6), author=User(user_id=11111, first_name='Bob', username=None), text='Hello there!')
```
```
bad_message = {
    "message_id": 25045,
    "date": 1676769966,
    "from": {"id": 11111, "first_name": 42},
    "text": "Hello there!",
}
is_message(bad_message)

...
Traceback (most recent call last):
  File "/.../tutorial.py", line 95, in <module>
    is_message(bad_message)
  File "/.../tutorial.py", line 43, in is_message
    author=is_any_of(
           ^^^^^^^^^^
  File "/.../humbleparser.py", line 289, in _is_any_of
    raise ParseError(MultipleErrors(tuple(errors)))
humbleparser.ParseError: all possibilities failed:
    - at key 'sender_chat': Key 'sender_chat' not found
    - at key 'from': at key 'first_name': expected a string, got <class 'int'>
```

### Parsing the `UpdateBody`

```py
from humbleparser import map_parser, is_always

def is_update_body(source: object) -> UpdateBody:
    return is_any_of(
        map_parser(NewMessage, has_field("message", is_message)),
        map_parser(MessageEdited, has_field("message_edited", is_message)),
        is_always(UnsupportedUpdate(source)),
    )(source)
```
Hm... actually, we're not doing anything with the source besides passing it to other parsers.
Let's refactor our code slightly:
```py
from humbleparser import is_anything

is_update_body = is_any_of(
    map_parser(NewMessage, has_field("message", is_message)),
    map_parser(MessageEdited, has_field("message_edited", is_message)),
    map_parser(UnsupportedUpdate, is_anything),
)
```

<details>
  <summary>Better error messages</summary>

This `is_any_of` is useful when you have few options, but the error message will not be very clear
with 10 variants. We can give each "branch" a name:
```py
from humbleparser import is_any_of_described

is_update_body = is_any_of_described(
    (
        "New message",
        map_parser(NewMessage, has_field("message", is_message)),
    ),
    (
        "Message edited",
        map_parser(MessageEdited, has_field("message_edited", is_message)),
    ),
    (
        "Unsupported update",
        map_parser(UnsupportedUpdate, is_anything),
    ),
)
```

</details>

### Parsing the `Update`

```py
def is_update(source: object) -> Update:
    return Update(
        update_id=has_field("update_id", is_int)(source),
        body=is_update_body(source),
    )
```

<details>
  <summary>Let's see our parser in action:</summary>

```py
>>> is_update({
...     "update_id": 257,
...     "message": {
...         "message_id": 100,
...         "date": 1676769964,
...         "sender_chat": {"id": 666, "title": "Some Chat"},
...     },
... })
...
Update(
    update_id=257,
    body=NewMessage(
        message=Message(
            message_id=100,
            sent_at=datetime.datetime(2023, 2, 19, 4, 26, 4),
            author=Chat(chat_id=666, title='Some Chat'),
            text=None,
        ),
    ),
)

>>> is_update({
...     "update_id": 257,
...     "unknown_update": {
...         "duckies": 666,
...     },
... })
...
Update(update_id=258, body=UnsupportedUpdate(raw={'update_id': 258, 'unknown_update': {'duckies': 666}}))

>>> is_update({"update_id": "yes!"})
Traceback (most recent call last):
...
humbleparser.ParseError: at key 'update_id': expected integer, got <class 'str'>
```

</details>


### Making our parser more robust

What we ended up with isn't bad, but there are some issues, especially as we're going to scale
to accept more updates:

- **Performance.** The way `is_any_of` works is: it tries all the given options one by one
  until it finds an option that matches. This makes it very flexible, but it also means
  that if there are 100 options, the parser will potentially have to go through all
  the 100 options on every message.

  In our case, we can optimize this because we know what update we want to parse based
  on the second key present in the `Update` object.

- **Error handling and unknown updates.** What happens if Telegram gives us a `message_edited`
  update with a body that doesn't match our expectations? Right now the parser will classify that
  as an `UnsupportedUpdate`, and we'll probably ignore it. That's very bad! We want to get an
  error in that case.

Here's one way you can solve the second problem:

```py
from humbleparser import is_dict

def is_update_body(source: object) -> UpdateBody:
    raw_dict = is_dict(source)

    if "message" in raw_dict:
        return NewMessage(is_message(raw_dict["message"]))
    elif "message_edited" in raw_dict:
        return MessageEdited(is_message(raw_dict["message_edited"]))
    else:
        return UnsupportedUpdate(raw_dict)
```

This is still not perfect, we're going to accept updates which have both a `message` and
`message_edited`. And we're still have a time complexity of `O(update_kinds)`.

We can solve both of these problems with a dictionary lookup:

```py
from humbleparser import Expectation


_known_events = {
    "message": map_parser(NewMessage, is_message),
    "message_edited": map_parser(MessageEdited, is_message),
}


def is_update_body(source: object) -> UpdateBody:
    raw_dict = is_dict(source)
    keys = raw_dict.keys() - {"update_id"}
    if len(keys) != 1:
        raise ParseError(Expectation(expected="one key", actual=str(list(keys))))
    [event_type] = keys

    if event_type in _known_events:
        return _known_events[event_type](raw_dict[event_type])
    else:
        return UnsupportedUpdate(raw_dict)
```

<details>
  <summary>

### Advanced topic: Error values

  </summary>

### Error values

Do we want to raise an exception on an invalid update from Telegram?

When we poll Telegram, we must specify what update ID we want the updates to start with.
When we get update `#100`, we tell Telegram to send updates starting with `#101` next time.
So our "main loop" will look something like this:

```py
last_update = 0

while True:
    response = requests.get(f"{api_root}/getUpdates", query={"offset": last_update, "timeout": 2}).json()
    if not response["ok"]:
        logger.error(f"Oh no! We're not OK: {response!r}")
        time.sleep(5)
        continue

    raw_updates = response["result"]
    for raw_update in raw_updates:
        try:
            update = is_update(raw_update)
        except ParseError as exc:
            logger.error("Wow, telegram sent us something stupid. ", exc_info=exc)
        else:
            last_update = max(last_update, update.id + 1)
            process_update(update)
```

Do you see the problem? If we get an invalid update, we ignore its ID! If that was the
only update in a while, on the next iteration we're going to ask for the same update, without a timeout.
Telegram will be very mad and will put us in the dreaded [429 Jail](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/429).

Another point is that we might want to still process updates that weren't quite right. Perhaps
we want to keep track of update statistics in `process_update`, or something else.

```diff
+ from humbleparser improt ErrorValue

+ @dataclass(frozen=True)
+ class InvalidUpdateReceived:
+     error: ErrorValue
+     raw: object

  UpdateBody = Union[
      NewMessage,
      MessageEdited,
      UnsupportedUpdate,
+     InvalidUpdateReceived,
  ]
```

An `ErrorValue` is a representation of what exactly went wrong during parsing.
It contains some clue as to what went wrong and where.

<details>
  <summary>Source code for `ErrorValue`</summary>

```py
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
```

</details>

Here's how we can adjust the `is_update_body` parser to accomodate this design:
```py
_known_events = {
    "message": map_parser(NewMessage, is_message),
    "message_edited": map_parser(MessageEdited, is_message),
}


def is_update_body(source: object) -> UpdateBody:
    raw_dict = is_dict(source)
    keys = raw_dict.keys() - {"update_id"}
    if len(keys) != 1:
        error = Expectation(expected="one key", actual=str(list(keys)))
        return InvalidUpdateReceived(error, source)
    [event_type] = keys

    event_payload = raw_dict[event_type]
    if event_type in _known_events:
        try:
            return _known_events[event_type](event_payload)
        except ParseError as exc:
            return InvalidUpdateReceived(exc.error, event_payload)
    else:
        return UnsupportedUpdate(raw_dict)
```

</details>

### Conclusion

A short recap on `humbleparser`:

- A parser is a function that accepts an objects and either returns its parsed version, or raises `ParseError`
- To parse a dictionary with known fields, use `has_field`
- If the field can be missing, use `has_optional_field` instead
- To try several options in order, use `any_of`
- To adjust the output of an already existing parser, use `map_parser`
- To accept any object at all, use `is_anything`
- If you don't see how to combine existing parsers together in a nice way, write your own from scratch.
