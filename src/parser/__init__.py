"""Parser module for CSV and event log processing."""

from .csv_loader import load_csv, CSVLoader

__all__ = ["load_csv", "CSVLoader"]
