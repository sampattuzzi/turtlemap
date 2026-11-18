from pathlib import Path
from typing import Any, Callable

from code_blueprints.analysis.project import Project

ProjectFactory = Callable[[dict[str, str]], Project]

SHOP = {
    "web/src/models.ts": """
        export interface Priced {
          price(): number;
        }

        export enum Size { Small, Large = 10 }

        export class Basket implements Priced {
          private items: Item[] = [];

          constructor(private readonly owner: string) {}

          add(item: Item): void {
            this.items.push(item);
          }

          price(): number {
            return this.items.reduce((sum, item) => sum + item.cost, 0);
          }
        }

        export class Item {
          constructor(public cost: number) {}
        }
    """,
    "web/src/checkout.ts": """
        import { Basket, Item } from "./models";
        import pricing from "./pricing";

        export const checkout = (owner: string): number => {
          const basket = new Basket(owner);
          basket.add(new Item(3));
          return pricing(basket.price());
        };
    """,
    "web/src/pricing/index.ts": """
        export default function withTax(amount: number): number {
          return amount * 1.2;
        }
    """,
}


def symbol(overview: dict[str, Any], path: str, qual: str) -> dict[str, Any]:
    module = next(m for m in overview["modules"] if m["path"] == path)
    return next(s for s in module["symbols"] if s["qual"] == qual)


def edges(overview: dict[str, Any]) -> set[tuple[str, str, str]]:
    ids = overview["edges"]["ids"]
    return {
        (ids[row[0]], ids[row[1]], kind)
        for row in overview["edges"]["rows"]
        for kind in row[2].split(",")
    }


def functions(project: Project, path: str) -> list[str]:
    module = project.workspace.module(path)
    assert module is not None
    return list(module.functions)


def test_lists_classes_interfaces_and_enums(make_project: ProjectFactory) -> None:
    overview = make_project(SHOP).overview()

    assert symbol(overview, "web/src/models.ts", "Priced")["stereo"] == "interface"
    assert symbol(overview, "web/src/models.ts", "Size")["members"] == [
        ["Small", "0"],
        ["Large", "10"],
    ]
    assert symbol(overview, "web/src/models.ts", "Basket")["kind"] == "class"


def test_reads_parameter_properties_as_fields(make_project: ProjectFactory) -> None:
    basket = symbol(make_project(SHOP).overview(), "web/src/models.ts", "Basket")

    assert dict((name, pin["label"]) for name, pin in basket["fields"]) == {
        "items": "Item[]",
        "owner": "string",
    }


def test_links_a_class_to_the_interface_it_implements(
    make_project: ProjectFactory,
) -> None:
    found = edges(make_project(SHOP).overview())

    assert (
        "cls:web/src/models.ts:Basket",
        "cls:web/src/models.ts:Priced",
        "realizes",
    ) in found


def test_links_calls_and_constructions_across_modules(
    make_project: ProjectFactory,
) -> None:
    found = edges(make_project(SHOP).overview())

    assert (
        "fn:web/src/checkout.ts:checkout",
        "cls:web/src/models.ts:Basket",
        "creates",
    ) in found
    assert (
        "fn:web/src/checkout.ts:checkout",
        "m:web/src/models.ts:Basket.add",
        "calls",
    ) in found
    assert (
        "fn:web/src/checkout.ts:checkout",
        "fn:web/src/pricing/index.ts:withTax",
        "calls",
    ) in found


def test_turns_arrow_functions_bound_to_names_into_functions(
    make_project: ProjectFactory,
) -> None:
    project = make_project(SHOP)

    assert functions(project, "web/src/checkout.ts") == ["checkout"]


def test_names_anonymous_callbacks_after_the_call_that_takes_them(
    make_project: ProjectFactory,
) -> None:
    project = make_project({"app/basket.test.ts": """
                describe("adding items", () => {
                  it("counts them", () => {});
                });
                describe("adding items", () => {});
                window.addEventListener("load", function () {
                  start();
                });
            """})

    assert functions(project, "app/basket.test.ts") == [
        "describe(adding items)",
        "describe(adding items) 2",
        "addEventListener(load)",
    ]


def test_names_object_methods_after_their_object(
    make_project: ProjectFactory,
) -> None:
    project = make_project({"app/api.js": """
                export const api = {
                  load(id) {
                    return fetch(id);
                  },
                  save: async (item) => {
                    await fetch(item);
                  },
                };

                export function refresh() {
                  return api.load(1);
                }
            """})

    assert functions(project, "app/api.js") == ["api.load", "api.save", "refresh"]
    assert (
        "fn:app/api.js:refresh",
        "fn:app/api.js:api.load",
        "calls",
    ) in edges(project.overview())


def test_treats_wrapped_functions_as_decorated_functions(
    make_project: ProjectFactory,
) -> None:
    project = make_project({"app/Card.tsx": """
                import { memo, useCallback } from "react";

                export const Card = memo(function Card({ title }: { title: string }) {
                  const onClick = useCallback(() => {
                    console.log(title);
                  }, [title]);
                  return <button onClick={onClick}>{title}</button>;
                });
            """})

    module = project.workspace.module("app/Card.tsx")
    assert module is not None
    assert list(module.functions) == ["Card"]
    decorators = module.functions["Card"].node.decorators
    assert [module.language.text(decorator) for decorator in decorators] == ["memo"]


def test_treats_jsx_components_as_calls(make_project: ProjectFactory) -> None:
    project = make_project(
        {
            "app/Button.tsx": """
                export function Button({ label }: { label: string }) {
                  return <button>{label}</button>;
                }
            """,
            "app/Page.tsx": """
                import { Button } from "./Button";

                export function Page() {
                  return (
                    <main>
                      <Button label="Save" />
                    </main>
                  );
                }
            """,
        }
    )

    assert (
        "fn:app/Page.tsx:Page",
        "fn:app/Button.tsx:Button",
        "calls",
    ) in edges(project.overview())


def test_resolves_tsconfig_path_aliases(make_project: ProjectFactory) -> None:
    project = make_project(
        {
            "web/tsconfig.json": """
                {
                  // comments and trailing commas are allowed here
                  "compilerOptions": {
                    "paths": { "@lib/*": ["./src/lib/*"], },
                  },
                }
            """,
            "web/src/lib/format.ts": """
                export function format(value: number): string {
                  return value.toFixed(2);
                }
            """,
            "web/src/view.ts": """
                import { format } from "@lib/format";

                export function show(): string {
                  return format(1);
                }
            """,
        }
    )

    assert (
        "fn:web/src/view.ts:show",
        "fn:web/src/lib/format.ts:format",
        "calls",
    ) in edges(project.overview())


def test_follows_names_re_exported_from_a_barrel(
    make_project: ProjectFactory,
) -> None:
    project = make_project(
        {
            "app/theme/spacing.ts": """
                export function gap(size: number): number {
                  return size * 4;
                }
            """,
            "app/theme/index.ts": """
                export * from "./spacing";
            """,
            "app/screen.ts": """
                import { gap } from "./theme";

                export function layout(): number {
                  return gap(2);
                }
            """,
        }
    )

    assert (
        "fn:app/screen.ts:layout",
        "fn:app/theme/spacing.ts:gap",
        "calls",
    ) in edges(project.overview())


def test_links_a_js_specifier_to_the_typescript_file_it_compiles_from(
    make_project: ProjectFactory,
) -> None:
    project = make_project(
        {
            "web/core/dom.ts": """
                export function el(tag: string): string {
                  return tag;
                }
            """,
            "web/map/view.ts": """
                import { el } from '../core/dom.js';
                export function draw(): string {
                  return el('div');
                }
            """,
        }
    )

    assert (
        "fn:web/map/view.ts:draw",
        "fn:web/core/dom.ts:el",
        "calls",
    ) in edges(project.overview())


def test_links_classic_scripts_through_their_shared_globals(
    make_project: ProjectFactory,
) -> None:
    project = make_project(
        {
            "static/util.js": """
                const LIMIT = 10;
                function clamp(value) {
                  return Math.min(value, LIMIT);
                }
            """,
            "static/app.js": """
                function render(value) {
                  return clamp(value) + LIMIT;
                }
            """,
        }
    )

    found = edges(project.overview())

    assert ("fn:static/app.js:render", "fn:static/util.js:clamp", "calls") in found
    assert ("fn:static/app.js:render", "c:static/util.js:LIMIT", "reads") in found


def test_ignores_locals_that_share_a_name_with_another_script(
    make_project: ProjectFactory,
) -> None:
    project = make_project(
        {
            "static/util.js": """
                function clamp(value) {
                  return value;
                }
            """,
            "static/app.js": """
                function render(items) {
                  const clamp = items.length;
                  return clamp + 1;
                }
            """,
        }
    )

    assert not any(
        source == "fn:static/app.js:render"
        for source, _, _ in edges(project.overview())
    )


def test_keeps_python_and_javascript_modules_with_the_same_name_apart(
    make_project: ProjectFactory,
) -> None:
    project = make_project(
        {
            "tokens.ts": """
                export function encode(value: string): string {
                  return value;
                }
            """,
            "service.py": """
                import tokens

                def sign(value: str) -> str:
                    return tokens.encode(value)
            """,
        }
    )

    found = edges(project.overview())

    assert ("fn:service.py:sign", "libn:tokens.encode", "calls") in found


def test_builds_blueprints_for_every_kind_of_statement(
    make_project: ProjectFactory,
) -> None:
    project = make_project({"app/everything.ts": """
                export async function* everything(items: number[], flag?: boolean) {
                  let total = 0;
                  const { first, ...rest } = { first: 1, second: 2 };
                  const [head, ...tail] = items;
                  for (let i = 0; i < items.length; i++) total += items[i] ** 2;
                  for (const item of items) { if (item % 2 === 0) continue; total -= item; }
                  for (const key in rest) total += key.length;
                  while (total > 100) { total >>= 1; }
                  do { total--; } while (total > 50);
                  switch (total) {
                    case 1:
                    case 2:
                      total = -total;
                      break;
                    default:
                      total = total ?? 0;
                  }
                  try {
                    total = flag ? total / 2 : total | 1;
                  } catch ({ message }) {
                    throw new Error(`failed: ${message}`);
                  } finally {
                    total &&= ~total;
                  }
                  const label = typeof head === "number" && !(tail instanceof Array) || head in rest;
                  delete rest.second;
                  yield* tail.map((value) => value << 1).filter(Boolean);
                  return { total, label, first, sum: tail?.at(0)! as number, items: [...items] };
                }
            """})

    graph = project.function("app/everything.ts", "everything")

    assert graph is not None
    switch = next(
        node for node in graph["graph"]["nodes"] if node["title"] == "Switch total"
    )
    assert switch["execOuts"] == ["case 1, 2", "default"]


def test_keeps_callback_parameters_inside_their_callback(
    make_project: ProjectFactory,
) -> None:
    project = make_project(
        {
            "static/util.js": """
                function clamp(value) {
                  return value;
                }
                function el(tag) {
                  return tag;
                }
            """,
            "static/app.js": """
                function render(items) {
                  items.map((clamp) => clamp + 1);
                  items.forEach((el) => {
                    el.focus();
                  });
                  return clamp(1);
                }
            """,
        }
    )

    found = {
        (target, kind)
        for source, target, kind in edges(project.overview())
        if source == "fn:static/app.js:render"
    }

    assert found == {("fn:static/util.js:clamp", "calls")}


def test_picks_up_a_module_added_after_its_importer_was_read(
    make_project: ProjectFactory, tmp_path: Path
) -> None:
    project = make_project({"app/main.ts": """
                import { helper } from "./helper";

                export function run(): number {
                  return helper();
                }
            """})
    project.overview()
    (tmp_path / "app/helper.ts").write_text(
        "export function helper(): number {\n  return 1;\n}\n"
    )
    project.reload()

    assert (
        "fn:app/main.ts:run",
        "fn:app/helper.ts:helper",
        "calls",
    ) in edges(project.overview())
