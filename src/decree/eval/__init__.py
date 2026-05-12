"""decree.eval — labeled-query retrieval-eval harness (SPEC-012).

Public re-exports for the harness:

    from decree.eval import (
        Query, QuerySet, load_query_set,
        RetrievalMethod, KeywordBaseline, METHODS,
        run_evaluation, RunReport, MethodResult,
        freeze_baseline, read_baseline,
    )
"""

from decree.eval.methods import METHODS, KeywordBaseline, RetrievalMethod
from decree.eval.runner import (
    MethodResult,
    RunReport,
    freeze_baseline,
    read_baseline,
    run_evaluation,
)
from decree.eval.schema import Query, QuerySet, load_query_set

__all__ = [
    "Query",
    "QuerySet",
    "load_query_set",
    "RetrievalMethod",
    "KeywordBaseline",
    "METHODS",
    "MethodResult",
    "RunReport",
    "run_evaluation",
    "freeze_baseline",
    "read_baseline",
]
