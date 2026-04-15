"""Main data pipeline orchestrator."""

import json
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from ..parser.csv_loader import CSVLoader
from ..models.event import Event
from ..models.activity import Activity, EventActivityMapping
from ..inference.event_grouper import EventGrouper
from ..inference.activity_inferrer import ActivityInferrer
from ..mapping.event_activity_mapper import EventActivityMapper


@dataclass
class PipelineResult:
    """Result of running the data pipeline."""

    activities: List[Activity]
    mappings: List[EventActivityMapping]
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
            f"Average confidence: {self.statistics.get('avg_confidence', 0):.2f}",
            "",
            "Activities:",
        ]

        for i, mapping in enumerate(self.mappings, 1):
            lines.append(
                f"  {i}. {mapping.activity.name} (confidence: {mapping.confidence:.2f})"
            )

        return "\n".join(lines)


class DataPipeline:
    """Main orchestrator for the UI log analysis pipeline."""

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

        self.loader = CSVLoader()
        self.grouper = EventGrouper(group_attributes)
        self.inferrer = ActivityInferrer(llm_client)
        self.mapper = EventActivityMapper(self.grouper, self.inferrer)

    def run(self) -> PipelineResult:
        """
        Run the complete data pipeline.

        Returns:
            PipelineResult with activities and mappings
        """
        events = self.loader.load(self.csv_path)

        mappings = self.mapper.map(events)
        activities = [m.activity for m in mappings]

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
            activities=activities, mappings=mappings, statistics=statistics
        )
