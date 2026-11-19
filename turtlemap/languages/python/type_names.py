from turtlemap.languages.language import TypeNames

_LIST_TYPES = frozenset(
    {
        "list",
        "List",
        "Sequence",
        "MutableSequence",
        "Iterable",
        "Iterator",
        "Collection",
        "Generator",
        "AsyncIterator",
        "AsyncIterable",
        "AsyncGenerator",
        "deque",
        "Deque",
        "tuple",
        "Tuple",
        "set",
        "Set",
        "frozenset",
        "FrozenSet",
        "AbstractSet",
        "MutableSet",
        "KeysView",
        "ValuesView",
        "NDArray",
        "ndarray",
    }
)

_MAP_TYPES = frozenset(
    {
        "dict",
        "Dict",
        "Mapping",
        "MutableMapping",
        "FrozenDict",
        "defaultdict",
        "DefaultDict",
        "OrderedDict",
        "Counter",
        "ChainMap",
    }
)

_SEQUENCE_ANNOTATIONS = frozenset(
    {
        "list",
        "List",
        "Sequence",
        "MutableSequence",
        "Iterable",
        "Iterator",
        "Collection",
        "set",
        "Set",
        "frozenset",
        "FrozenSet",
        "AbstractSet",
        "deque",
        "Deque",
        "Generator",
        "AsyncIterator",
        "AsyncIterable",
        "AsyncGenerator",
        "KeysView",
        "ValuesView",
    }
)

_MAPPING_ANNOTATIONS = frozenset(
    {
        "dict",
        "Dict",
        "Mapping",
        "MutableMapping",
        "FrozenDict",
        "defaultdict",
        "DefaultDict",
        "OrderedDict",
    }
)

PYTHON_TYPES = TypeNames(
    scalars={
        "bool": "bool",
        "int": "int",
        "float": "float",
        "complex": "float",
        "Decimal": "float",
        "float64": "float",
        "float32": "float",
        "int64": "int",
        "int32": "int",
        "str": "str",
        "bytes": "bytes",
        "bytearray": "bytes",
        "memoryview": "bytes",
        "None": "none",
        "NoneType": "none",
        "datetime": "time",
        "date": "time",
        "time": "time",
        "timedelta": "time",
        "Timestamp": "time",
        "Timedelta": "time",
        "tzinfo": "time",
        "ZoneInfo": "time",
        "Any": "any",
        "object": "any",
        "Path": "str",
        "PurePath": "str",
        "PurePosixPath": "str",
        "UUID": "str",
    },
    lists=_LIST_TYPES,
    maps=_MAP_TYPES,
    transparent=frozenset(
        {
            "Annotated",
            "Final",
            "ClassVar",
            "Required",
            "NotRequired",
            "ReadOnly",
            "Awaitable",
            "InitVar",
        }
    ),
    enum_bases=frozenset({"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag"}),
    struct_bases=frozenset(
        {"BaseModel", "NamedTuple", "TypedDict", "Struct", "BaseSettings", "RootModel"}
    ),
    struct_decorators=frozenset(
        {"dataclass", "attrs", "define", "frozen", "s", "dataclass_json"}
    ),
    interface_bases=frozenset({"Protocol", "ABC"}),
    model_bases=frozenset({"BaseModel", "BaseSettings", "RootModel"}),
    optional=frozenset({"Optional"}),
    union=frozenset({"Union"}),
    literal=frozenset({"Literal"}),
    callables=frozenset({"Callable", "Coroutine"}),
    class_types=frozenset({"type", "Type"}),
    awaitables=frozenset({"Coroutine"}),
    guards=frozenset({"TypeGuard", "TypeIs"}),
    tuples=frozenset({"tuple", "Tuple"}),
    class_variable=frozenset({"ClassVar"}),
    sequences=_SEQUENCE_ANNOTATIONS,
    mappings=_MAPPING_ANNOTATIONS,
)
