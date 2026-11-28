"""Data analysis computed by the harness, never by the model.

A CSV, TSV, XLSX file or a pasted table is read (``table``), each column is typed and profiled (``profile``),
analyses are suggested from the column types (``suggest``), questions are turned into a tiny safe query
(``ask`` -> ``query``) and run here, and every number the model writes about the result is checked (``verify``).
Charts of results use the richer spec of ``charts``. Pure standard library: nothing is added to the deployment.
"""

from birds.harness.analysis.ask import plan_question
from birds.harness.analysis.charts import auto_type, chart_from_result, normalize_spec
from birds.harness.analysis.profile import profile_table
from birds.harness.analysis.query import QueryError, run_query
from birds.harness.analysis.suggest import suggestions
from birds.harness.analysis.table import Table, TableError, read_table, read_text_table
from birds.harness.analysis.verify import check_numbers

__all__ = [
    "QueryError",
    "Table",
    "TableError",
    "auto_type",
    "chart_from_result",
    "check_numbers",
    "normalize_spec",
    "plan_question",
    "profile_table",
    "read_table",
    "read_text_table",
    "run_query",
    "suggestions",
]
