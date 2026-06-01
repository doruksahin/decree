"""decree.eval — labeled-query retrieval-eval harness (SPEC-01KT22NMRZXE5C42F6Z0ZY559A).

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
    "METHODS",
    "KeywordBaseline",
    "MethodResult",
    "Query",
    "QuerySet",
    "RetrievalMethod",
    "RunReport",
    "freeze_baseline",
    "load_query_set",
    "read_baseline",
    "run_evaluation",
]
