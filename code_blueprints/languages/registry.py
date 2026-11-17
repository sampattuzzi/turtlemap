from pathlib import PurePosixPath

from code_blueprints.languages.language import Language
from code_blueprints.languages.javascript import JavaScript
from code_blueprints.languages.python import Python

LANGUAGES: tuple[Language, ...] = (Python(), JavaScript())
EXTENSIONS: tuple[str, ...] = tuple(
    extension for language in LANGUAGES for extension in language.extensions
)
STDLIB_MODULES: frozenset[str] = frozenset(
    name for language in LANGUAGES for name in language.profile.stdlib_modules
)


def language_for(path: str) -> Language | None:
    for language in LANGUAGES:
        if language.handles(path):
            return language
    return None


def is_source(path: str) -> bool:
    language = language_for(path)
    return language is not None and language.includes(path)


def is_project_config(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.startswith(("tsconfig", "jsconfig")) and name.endswith(".json")
