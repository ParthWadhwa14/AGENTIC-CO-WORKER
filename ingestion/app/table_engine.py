from pathlib import Path
from typing import Any

import pandas as pd


class CSVTableEngine:
    """
    Executes safe pandas operations on a CSV file.

    This is not an LLM code executor yet.
    It provides predefined safe functions.
    """

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.df = pd.read_csv(file_path)
        self.df = self.df.fillna("")

    def row_count(self) -> int:
        return int(len(self.df))

    def columns(self) -> list[str]:
        return list(map(str, self.df.columns))

    def value_counts(self, column: str, top_k: int = 20) -> dict[str, int]:
        self._validate_column(column)

        counts = (
            self.df[column]
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .value_counts()
            .head(top_k)
        )

        return {str(k): int(v) for k, v in counts.items()}

    def filter_equals(
        self,
        column: str,
        value: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self._validate_column(column)

        result = self.df[
            self.df[column].astype(str).str.lower()
            == str(value).lower()
        ]

        return result.head(limit).to_dict(orient="records")

    def filter_contains(
        self,
        column: str,
        value: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self._validate_column(column)

        result = self.df[
            self.df[column]
            .astype(str)
            .str.lower()
            .str.contains(str(value).lower(), na=False)
        ]

        return result.head(limit).to_dict(orient="records")

    def numeric_summary(self, column: str) -> dict[str, float]:
        self._validate_column(column)

        series = pd.to_numeric(self.df[column], errors="coerce").dropna()

        if series.empty:
            raise ValueError(f"Column '{column}' is not numeric.")

        return {
            "count": int(series.count()),
            "mean": float(series.mean()),
            "median": float(series.median()),
            "min": float(series.min()),
            "max": float(series.max()),
            "std": float(series.std()) if len(series) > 1 else 0.0,
        }

    def groupby_count(
        self,
        group_column: str,
        top_k: int = 20,
    ) -> dict[str, int]:
        self._validate_column(group_column)

        result = (
            self.df[group_column]
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .value_counts()
            .head(top_k)
        )

        return {str(k): int(v) for k, v in result.items()}

    def groupby_numeric_agg(
        self,
        group_column: str,
        numeric_column: str,
        agg: str = "sum",
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        self._validate_column(group_column)
        self._validate_column(numeric_column)

        temp = self.df.copy()
        temp[numeric_column] = pd.to_numeric(
            temp[numeric_column],
            errors="coerce"
        )

        allowed_aggs = {"sum", "mean", "median", "min", "max", "count"}

        if agg not in allowed_aggs:
            raise ValueError(f"Unsupported aggregation: {agg}")

        grouped = (
            temp.groupby(group_column)[numeric_column]
            .agg(agg)
            .sort_values(ascending=False)
            .head(top_k)
            .reset_index()
        )

        return grouped.to_dict(orient="records")

    def date_range(
        self,
        date_column: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self._validate_column(date_column)

        temp = self.df.copy()
        temp[date_column] = pd.to_datetime(
            temp[date_column],
            errors="coerce"
        )

        result = temp[temp[date_column].notna()]

        if start_date:
            result = result[result[date_column] >= pd.to_datetime(start_date)]

        if end_date:
            result = result[result[date_column] <= pd.to_datetime(end_date)]

        return result.head(limit).to_dict(orient="records")

    def _validate_column(self, column: str):
        if column not in self.df.columns:
            raise ValueError(
                f"Column '{column}' not found. "
                f"Available columns: {list(self.df.columns)}"
            )