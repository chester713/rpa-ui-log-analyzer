"""Main data pipeline orchestrator with pattern matching."""

import json
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from ..parser.csv_loader import CSVLoader
from ..models.event import Event
from ..models.activity import Activity, EventActivityMapping
from ..models.pattern import MethodRecommendation
from ..inference.event_grouper import EventGrouper
from ..inference.activity_inferrer import ActivityInferrer
from ..mapping.event_activity_mapper import EventActivityMapper
from ..matching.pattern_matcher import get_context_from_events
from ..matching.output_formatter import RecommendationFormatter


@dataclass
class PipelineResult:
    """Result of running the data pipeline."""

    activities: List[Activity]
    mappings: List[EventActivityMapping]
    recommendations: List[MethodRecommendation]
    statistics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "activities": [
                {
                    "name": a.name,
                    "confidence": a.confidence,
                    "evidence": a.evidence,
                    "source_events": a.source_events,
                }
                for a in self.activities
            ],
            "mappings": [m.to_dict() for m in self.mappings],
            "recommendations": [r.to_dict() for r in self.recommendations],
            "statistics": self.statistics,
        }

    def to_json(self, filepath: str) -> None:
        """Write result to JSON file."""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "=== RPA UI Log Analyzer Results ===",
            f"Total activities inferred: {len(self.activities)}",
            f"Total event-to-activity mappings: {len(self.mappings)}",
            f"Total recommendations: {len(self.recommendations)}",
            f"Average confidence: {self.statistics.get('avg_confidence', 0):.2f}",
            "",
            "Activities:",
        ]

        for i, mapping in enumerate(self.mappings, 1):
            lines.append(
                f"  {i}. {mapping.activity.name} (confidence: {mapping.confidence:.2f})"
            )

        lines.append("")
        lines.append("Recommendations:")
        for i, rec in enumerate(self.recommendations, 1):
            lines.append(
                f"  {i}. {rec.activity_name} -> {rec.method} ({rec.execution_environment})"
            )

        return "\n".join(lines)


class DataPipeline:
    """Main orchestrator for the UI log analysis pipeline with pattern matching."""

    def __init__(
        self,
        csv_path: str,
        llm_client=None,
        group_attributes: Optional[List[str]] = None,
    ):
        """
        Initialize DataPipeline.

        Args:
            csv_path: Path to CSV UI log file
            llm_client: Optional LLM client for activity inference
            group_attributes: Optional list of attributes for event grouping
        """
        self.csv_path = csv_path
        self.llm_client = llm_client

        self.loader = CSVLoader(llm_client)
        self.grouper = EventGrouper(group_attributes)
        self.inferrer = ActivityInferrer(llm_client)
        self.mapper = EventActivityMapper(self.grouper, self.inferrer)
        self.formatter = RecommendationFormatter()

    def run(self) -> PipelineResult:
        """
        Run the complete data pipeline.

        Returns:
            PipelineResult with activities, mappings, and recommendations
        """
        events = self.loader.load(self.csv_path)

        mappings = self.mapper.map(events)
        activities = [m.activity for m in mappings]

        recommendations = self._create_recommendations(mappings)

        statistics = {
            "total_events": len(events),
            "total_groups": len(mappings),
            "avg_events_per_group": len(events) / len(mappings) if mappings else 0,
            "avg_confidence": sum(m.confidence for m in mappings) / len(mappings)
            if mappings
            else 0,
            "grouper_stats": self.grouper.get_group_summary(
                self.grouper.group_events(events)
            ),
            "mapping_stats": self.mapper.get_mapping_summary(mappings),
        }

        return PipelineResult(
            activities=activities,
            mappings=mappings,
            recommendations=recommendations,
            statistics=statistics,
        )

    def _create_recommendations(
        self, mappings: List[EventActivityMapping]
    ) -> List[MethodRecommendation]:
        """Create method recommendations from activity mappings."""
        from ..matching import PATTERNS, PatternMatcher

        recommendations = []
        matcher = PatternMatcher(PATTERNS)

        for mapping in mappings:
            activity = mapping.activity
            events = mapping.events
            context = get_context_from_events(events)

            pattern = matcher.match(activity, events, context)
            method = pattern.get_method_for_context(context) if pattern else None

            event_indices = [e.row_index for e in events if e.row_index is not None]

            context_switch = mapping.attribute_breakdown.get("context_switch", False)
            context_switch_from = mapping.attribute_breakdown.get("previous_app")
            context_switch_to = mapping.attribute_breakdown.get("current_app")

            action, obj = self._parse_activity_name(activity.name)

            recommendation = MethodRecommendation(
                activity_name=activity.name,
                activity_action=action,
                activity_object=obj,
                events=event_indices,
                execution_environment=context,
                pattern=pattern,
                method=method,
                method_category=pattern.category if pattern else None,
                confidence=activity.confidence,
                context_switch=context_switch,
                context_switch_from=context_switch_from,
                context_switch_to=context_switch_to,
            )
            recommendations.append(recommendation)

        return recommendations

    def _parse_activity_name(self, activity_name: str) -> tuple:
        """Parse activity name into action and object."""
        parts = activity_name.split()
        if len(parts) >= 2:
            action = parts[0]
            obj = " ".join(parts[1:])
        else:
            action = activity_name
            obj = ""
        return action, obj
