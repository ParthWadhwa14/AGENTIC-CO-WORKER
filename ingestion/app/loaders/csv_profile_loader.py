from pathlib import Path
from uuid import uuid4
from typing import Any

import pandas as pd

from app.models import ParsedElement


class CSVProfileLoader:
    """
    CSV loader for large datasets.

    Instead of embedding every row, this loader creates compact semantic
    profile chunks that describe the dataset. The raw CSV should still be
    stored separately and queried using pandas/DuckDB at retrieval time.
    """

    source_type = "csv"

    def load(
        self,
        file_path: str,
        document_id: str | None = None,
        sample_rows: int = 8,
        top_k_values: int = 10,
    ) -> list[ParsedElement]:
        document_id = document_id or str(uuid4())
        path = Path(file_path)

        df = pd.read_csv(file_path)
        df = df.replace({pd.NA: None})
        df = df.fillna("")

        elements: list[ParsedElement] = []

        overview_text = self._build_overview(path.name, df)
        schema_text = self._build_schema(path.name, df)
        missing_text = self._build_missing_values(path.name, df)
        numeric_text = self._build_numeric_summary(path.name, df)
        categorical_text = self._build_categorical_summary(
            path.name,
            df,
            top_k_values=top_k_values,
        )
        datetime_text = self._build_datetime_summary(path.name, df)
        sample_text = self._build_sample_rows(
            path.name,
            df,
            sample_rows=sample_rows,
        )
        query_hint_text = self._build_query_hints(path.name, df)

        chunks = [
            ("csv_overview", overview_text),
            ("csv_schema", schema_text),
            ("csv_missing_values", missing_text),
            ("csv_numeric_summary", numeric_text),
            ("csv_categorical_summary", categorical_text),
            ("csv_datetime_summary", datetime_text),
            ("csv_sample_rows", sample_text),
            ("csv_query_hints", query_hint_text),
        ]

        for element_type, text in chunks:
            if text.strip():
                elements.append(
                    ParsedElement(
                        document_id=document_id,
                        source_type=self.source_type,
                        file_name=path.name,
                        element_type=element_type,
                        text=text,
                        metadata={
                            "file_path": str(path),
                            "row_count": int(len(df)),
                            "column_count": int(len(df.columns)),
                            "columns": list(map(str, df.columns)),
                            "large_table_mode": True,
                        },
                    )
                )

        return elements

    def _build_overview(self, file_name: str, df: pd.DataFrame) -> str:
        return f"""
CSV Dataset Overview

File name: {file_name}
Number of rows: {len(df)}
Number of columns: {len(df.columns)}

Column names:
{", ".join(map(str, df.columns))}

This is a structured tabular dataset. For exact row-level questions,
filters, aggregations, counts, sorting, grouping, or calculations, the
raw CSV should be queried using pandas or SQL instead of relying only
on vector search.
""".strip()

    def _build_schema(self, file_name: str, df: pd.DataFrame) -> str:
        lines = [
            "CSV Schema",
            f"File name: {file_name}",
            "",
            "Columns:",
        ]

        for col in df.columns:
            series = df[col]
            dtype = str(series.dtype)
            non_null_count = int(series.astype(str).replace("", pd.NA).dropna().shape[0])
            unique_count = int(series.nunique(dropna=True))

            sample_values = (
                series.astype(str)
                .replace("", pd.NA)
                .dropna()
                .drop_duplicates()
                .head(5)
                .tolist()
            )

            lines.append(
                f"- Column: {col}\n"
                f"  Data type: {dtype}\n"
                f"  Non-empty values: {non_null_count}\n"
                f"  Unique values: {unique_count}\n"
                f"  Sample values: {sample_values}"
            )

        return "\n".join(lines)

    def _build_missing_values(self, file_name: str, df: pd.DataFrame) -> str:
        lines = [
            "CSV Missing Value Summary",
            f"File name: {file_name}",
            "",
        ]

        total_rows = len(df)

        for col in df.columns:
            empty_count = int(
                df[col]
                .astype(str)
                .str.strip()
                .eq("")
                .sum()
            )

            missing_percentage = (
                round((empty_count / total_rows) * 100, 2)
                if total_rows > 0
                else 0
            )

            lines.append(
                f"- {col}: {empty_count} missing/empty values "
                f"({missing_percentage}%)"
            )

        return "\n".join(lines)

    def _build_numeric_summary(self, file_name: str, df: pd.DataFrame) -> str:
        numeric_df = df.copy()

        numeric_columns = []

        for col in numeric_df.columns:
            converted = pd.to_numeric(numeric_df[col], errors="coerce")
            valid_ratio = converted.notna().mean()

            if valid_ratio > 0.6:
                numeric_df[col] = converted
                numeric_columns.append(col)

        if not numeric_columns:
            return f"""
CSV Numeric Summary

File name: {file_name}

No clearly numeric columns were detected.
""".strip()

        lines = [
            "CSV Numeric Summary",
            f"File name: {file_name}",
            "",
        ]

        desc = numeric_df[numeric_columns].describe().T

        for col in numeric_columns:
            stats = desc.loc[col]

            lines.append(
                f"- Numeric column: {col}\n"
                f"  Count: {int(stats['count'])}\n"
                f"  Mean: {round(float(stats['mean']), 4)}\n"
                f"  Std: {round(float(stats['std']), 4) if pd.notna(stats['std']) else None}\n"
                f"  Min: {round(float(stats['min']), 4)}\n"
                f"  25%: {round(float(stats['25%']), 4)}\n"
                f"  Median: {round(float(stats['50%']), 4)}\n"
                f"  75%: {round(float(stats['75%']), 4)}\n"
                f"  Max: {round(float(stats['max']), 4)}"
            )

        return "\n".join(lines)

    def _build_categorical_summary(
        self,
        file_name: str,
        df: pd.DataFrame,
        top_k_values: int = 10,
    ) -> str:
        lines = [
            "CSV Categorical Summary",
            f"File name: {file_name}",
            "",
        ]

        categorical_columns = []

        for col in df.columns:
            series = df[col].astype(str).str.strip()
            unique_count = series.replace("", pd.NA).dropna().nunique()

            # Heuristic:
            # A categorical column usually has repeated values.
            if unique_count <= min(100, max(20, len(df) * 0.2)):
                categorical_columns.append(col)

        if not categorical_columns:
            return f"""
CSV Categorical Summary

File name: {file_name}

No clearly categorical columns were detected.
""".strip()

        for col in categorical_columns:
            value_counts = (
                df[col]
                .astype(str)
                .str.strip()
                .replace("", pd.NA)
                .dropna()
                .value_counts()
                .head(top_k_values)
            )

            lines.append(f"- Categorical column: {col}")
            lines.append(f"  Unique values: {df[col].nunique(dropna=True)}")
            lines.append("  Top values:")

            for value, count in value_counts.items():
                lines.append(f"    - {value}: {int(count)}")

            lines.append("")

        return "\n".join(lines)

    def _build_datetime_summary(self, file_name: str, df: pd.DataFrame) -> str:
        lines = [
            "CSV Date/Time Summary",
            f"File name: {file_name}",
            "",
        ]

        detected = False

        for col in df.columns:
            # Try parsing dates only if column name or values suggest dates.
            col_lower = str(col).lower()
            likely_date_name = any(
                key in col_lower
                for key in ["date", "time", "deadline", "created", "updated"]
            )

            if not likely_date_name:
                continue

            parsed = pd.to_datetime(df[col], errors="coerce")
            valid_ratio = parsed.notna().mean()

            if valid_ratio > 0.5:
                detected = True

                lines.append(
                    f"- Date/time column: {col}\n"
                    f"  Valid date values: {int(parsed.notna().sum())}\n"
                    f"  Earliest date: {parsed.min()}\n"
                    f"  Latest date: {parsed.max()}"
                )

        if not detected:
            return f"""
CSV Date/Time Summary

File name: {file_name}

No clearly parseable date/time columns were detected.
""".strip()

        return "\n".join(lines)

    def _build_sample_rows(
        self,
        file_name: str,
        df: pd.DataFrame,
        sample_rows: int = 8,
    ) -> str:
        if df.empty:
            return f"""
CSV Sample Rows

File name: {file_name}

The CSV has no rows.
""".strip()

        sample_df = df.head(sample_rows)

        lines = [
            "CSV Sample Rows",
            f"File name: {file_name}",
            f"Showing first {min(sample_rows, len(df))} rows.",
            "",
        ]

        for index, row in sample_df.iterrows():
            parts = [f"{col}: {row[col]}" for col in df.columns]
            lines.append(f"Row {index + 1}: " + " | ".join(parts))

        return "\n".join(lines)

    def _build_query_hints(self, file_name: str, df: pd.DataFrame) -> str:
        columns = list(map(str, df.columns))

        return f"""
CSV Query Hints

File name: {file_name}

This dataset can answer questions involving:
- row counts
- column descriptions
- filtering by column values
- grouping and aggregation
- sorting
- missing value analysis
- numeric statistics
- categorical value counts
- date range filtering if date columns exist

Available columns:
{", ".join(columns)}

For exact questions, use pandas or SQL on the raw CSV file.
For semantic discovery, use vector search over this CSV profile.
""".strip()