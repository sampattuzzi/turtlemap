FORMULAS = {
    "class": "LCOM4: methods (constructors left out) are linked when they share a field of the class or call each other; the count of linked groups is the score, 1 is cohesive.",
    "module": "Linked groups among the module's classes and functions: two are linked when one uses the other or both touch the same module constant (constants link members but are not members themselves), plus relational cohesion = internal links / (internal + links to other project modules).",
    "package": "Linked groups among the package's modules, plus relational cohesion = links inside the package / (inside + links to the rest of the project).",
    "function": "Independent dataflow strands: nodes joined by data wires, leaving out the parameters and the unpacking of self, so two strands share no value. Heuristic.",
    "coupling": "Edges between the two, each weighted by kind (inherits 4, realizes 3, writes 3, reads 2, creates/calls/has 1, uses 0.5), plus fields of a third party that both touch. Tight: inheritance, writing the other's fields, a cycle, or score >= 12. Moderate: score >= 4, more than 3 distinct members touched, or a shared field that either writes. Otherwise loose.",
    "instability": "Instability = Ce / (Ca + Ce): Ca counts the project modules that depend on this one (tests left out), Ce the project modules it depends on.",
}
