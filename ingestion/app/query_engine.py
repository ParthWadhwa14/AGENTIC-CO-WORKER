from app.qdrant_store import QdrantStore
from app.table_engine import CSVTableEngine


class QueryEngine:
    def __init__(self):
        self.store = QdrantStore()

    def answer_csv_query_simple(self, query: str):
        """
        1. Search Qdrant for relevant CSV profile chunks.
        2. Get original CSV file_path from metadata.
        3. Use pandas-based CSVTableEngine for exact operations.
        """

        results = self.store.search(
            query=query,
            limit=5,
            source_type="csv",
        )

        if not results:
            return {
                "type": "error",
                "message": "No relevant CSV found."
            }

        best = results[0]
        payload = best.payload

        file_name = payload.get("file_name")
        metadata = payload.get("metadata", {})
        file_path = metadata.get("file_path")
        columns = metadata.get("columns", [])

        if not file_path:
            return {
                "type": "error",
                "message": "CSV file path not found in Qdrant metadata."
            }

        engine = CSVTableEngine(file_path)

        q = query.lower()

        # Very basic routing logic for now.
        # Later, replace this with an LLM tool planner.

        if "how many rows" in q or "row count" in q or "number of rows" in q:
            return {
                "type": "csv_answer",
                "file": file_name,
                "operation": "row_count",
                "answer": engine.row_count(),
            }

        if "columns" in q or "column names" in q:
            return {
                "type": "csv_answer",
                "file": file_name,
                "operation": "columns",
                "answer": engine.columns(),
            }

        if "pending" in q and "status" in [c.lower() for c in columns]:
            status_col = self._find_column(columns, "status")

            return {
                "type": "csv_answer",
                "file": file_name,
                "operation": "filter_equals",
                "column": status_col,
                "value": "Pending",
                "answer": engine.filter_equals(
                    column=status_col,
                    value="Pending",
                    limit=20,
                ),
            }

        if "value count" in q or "value counts" in q:
            return {
                "type": "csv_answer",
                "file": file_name,
                "message": "I found the CSV, but you need to specify which column to count.",
                "available_columns": columns,
            }

        return {
            "type": "csv_answer",
            "file": file_name,
            "message": "Relevant CSV found, but no predefined table operation matched this query yet.",
            "available_columns": columns,
            "matched_chunk": payload.get("chunk_type"),
            "retrieval_score": best.score,
        }

    def _find_column(self, columns: list[str], target: str) -> str:
        for col in columns:
            if col.lower() == target.lower():
                return col

        for col in columns:
            if target.lower() in col.lower():
                return col

        raise ValueError(f"No column similar to '{target}' found.")