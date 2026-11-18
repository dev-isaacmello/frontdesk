"""CST-2: which model answers which node, for which plan and at which budget level."""

from dataclasses import dataclass
from typing import Literal

type Node = Literal["classify", "plan"]
type BudgetLevel = Literal["normal", "economy", "exhausted"]


@dataclass(frozen=True)
class Routes:
    default: str
    """The model of every call that no rule below sends elsewhere."""

    classify: str | None = None
    """The classifier's model. A yes or no over one message needs less than planning does."""

    pro: str | None = None
    """The planner's model for tenants on the pro plan."""

    economy: str | None = None
    """The model of every call of a tenant that has reached its monthly budget."""

    def model_for(self, node: Node, plan: str, level: BudgetLevel) -> str:
        if level == "economy" and self.economy:
            return self.economy
        if node == "classify" and self.classify:
            return self.classify
        if node == "plan" and plan == "pro" and self.pro:
            return self.pro
        return self.default
