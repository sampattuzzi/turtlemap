import threading
from collections.abc import Callable, Hashable, Iterable, Iterator, MutableMapping
from contextlib import contextmanager
from typing import TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")

Keys = frozenset[str]
Remembered = MutableMapping[K, tuple[V, Keys]]


SOURCE = "src:"


def source_key(path: str) -> str:
    return SOURCE + path


class ReadLog:
    def __init__(self) -> None:
        self._local = threading.local()

    def note(self, key: str) -> None:
        frames = self._frames()
        if frames:
            frames[-1].add(key)

    def note_all(self, keys: Iterable[str]) -> None:
        frames = self._frames()
        if frames:
            frames[-1].update(keys)

    @contextmanager
    def recording(self) -> Iterator[set[str]]:
        frames = self._frames()
        frame: set[str] = set()
        frames.append(frame)
        try:
            yield frame
        finally:
            frames.pop()
            if frames:
                frames[-1].update(frame)

    def remembered(
        self, cache: Remembered[K, V], key: K, compute: Callable[[], V]
    ) -> V:
        found = cache.get(key)
        if found is not None:
            self.note_all(found[1])
            return found[0]
        with self.recording() as keys:
            value = compute()
        cache[key] = (value, frozenset(keys))
        return value

    def _frames(self) -> list[set[str]]:
        frames: list[set[str]] | None = getattr(self._local, "frames", None)
        if frames is None:
            frames = []
            self._local.frames = frames
        return frames
