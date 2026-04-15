"""Output formatter for pattern matching recommendations."""

import csv
from typing import List, Dict, Any
from ..models.pattern import MethodRecommendation


class RecommendationFormatter:
    """Formats pattern matching recommendations for output."""

    def format(self, recommendations: List[MethodRecommendation]) -> Dict[str, Any]:
        """
        Format recommendations as structured output.

        Args:
            recommendations: List of MethodRecommendation objects

        Returns:
            Dictionary with formatted recommendations
        """
        return {"recommendations": [rec.to_dict() for rec in recommendations]}

    def format_summary(self, recommendations: List[MethodRecommendation]) -> str:
        """
        Format recommendations as human-readable summary.

        Args:
            recommendations: List of MethodRecommendation objects

        Returns:
            Summary string
        """
        lines = [
            "=== RPA UI Log Analyzer - Method Recommendations ===",
            f"Total recommendations: {len(recommendations)}",
            "",
        ]

        for i, rec in enumerate(recommendations, 1):
            lines.append(f"--- Recommendation {i} ---")
            lines.append(f"  Activity: {rec.activity_name}")
            lines.append(f"  Events: {rec.events}")
            lines.append(f"  Environment: {rec.execution_environment}")
            lines.append(f"  Pattern: {rec.pattern.name if rec.pattern else 'None'}")
            lines.append(f"  Method: {rec.method or 'None'}")
            lines.append(f"  Category: {rec.method_category or 'None'}")
            lines.append(f"  Confidence: {rec.confidence:.2f}")
            lines.append("")

        return "\n".join(lines)

    def to_csv(self, recommendations: List[MethodRecommendation], output_path: str):
        """
        Export recommendations to CSV file.

        Args:
            recommendations: List of MethodRecommendation objects
            output_path: Path to output CSV file
        """
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Activity",
                    "Events",
                    "Environment",
                    "Pattern",
                    "Method",
                    "Category",
                    "Confidence",
                ]
            )

            for rec in recommendations:
                writer.writerow(
                    [
                        rec.activity_name,
                        ", ".join(map(str, rec.events)),
                        rec.execution_environment,
                        rec.pattern.name if rec.pattern else "",
                        rec.method or "",
                        rec.method_category or "",
                        f"{rec.confidence:.2f}",
                    ]
                )

    def to_json_file(
        self, recommendations: List[MethodRecommendation], output_path: str
    ):
        """
        Export recommendations to JSON file.

        Args:
            recommendations: List of MethodRecommendation objects
            output_path: Path to output JSON file
        """
        import json

        data = self.format(recommendations)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
