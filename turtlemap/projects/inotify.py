import os

from watchdog.observers.inotify import (
    InotifyEmitter,
    InotifyObserver,
    InotifyWatchGroup,
)

from turtlemap.analysis.workspace.files import is_ignored_folder


class PrunedInotifyObserver(InotifyObserver):
    def __init__(self) -> None:
        super().__init__()
        self._emitter_class = PrunedInotifyEmitter


class PrunedInotifyEmitter(InotifyEmitter):
    def on_thread_start(self) -> None:
        self._inotify = PrunedWatchGroup(
            self._inotify_fd,
            os.fsencode(self.watch.path),
            is_recursive=self.watch.is_recursive,
            event_mask=self.get_event_mask_from_filter(),
            follow_symlink=self.watch.follow_symlink,
        )


class PrunedWatchGroup(InotifyWatchGroup):
    def _add_all_callbacks(self, path: bytes) -> None:
        if path != self.path and _is_ignored(path):
            return
        self._add_callback(path)
        if not self.is_recursive or not os.path.isdir(path):
            return
        for folder, children, _ in os.walk(path, followlinks=self.follow_symlink):
            children[:] = [
                child
                for child in children
                if not _is_ignored(child)
                and (
                    self.follow_symlink
                    or not os.path.islink(os.path.join(folder, child))
                )
            ]
            for child in children:
                self._add_callback(os.path.join(folder, child))


def _is_ignored(path: bytes) -> bool:
    return is_ignored_folder(os.fsdecode(os.path.basename(path)))
