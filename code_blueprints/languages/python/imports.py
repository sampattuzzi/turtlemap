import ast

from code_blueprints.analysis import model as m
from code_blueprints.languages.python.nodes import span


class ImportLowering:
    def __init__(self, package: str) -> None:
        self.package = package

    def import_statement(self, node: ast.Import, line: int, end: int) -> m.Stmt:
        return m.Import(
            line,
            end,
            None,
            [m.ImportName(*span(a), a.name, a.asname, origin=a) for a in node.names],
            whole=True,
            origin=node,
        )

    def import_from(self, node: ast.ImportFrom, line: int, end: int) -> m.Stmt:
        base = self.from_base(node)
        return m.Import(
            line,
            end,
            base,
            [m.ImportName(*span(a), a.name, a.asname, origin=a) for a in node.names],
            level=node.level,
            whole=False,
            origin=node,
        )

    def from_base(self, node: ast.ImportFrom) -> str | None:
        if node.level == 0:
            return node.module or ""
        package_parts = self.package.split(".") if self.package else []
        if node.level - 1 > len(package_parts):
            return None
        kept = package_parts[: len(package_parts) - (node.level - 1)]
        if node.module:
            kept.append(node.module)
        return ".".join(kept)
