"""Main data pipeline orchestrator with pattern matching."""

import json
from dataclasses import dataclass
from typing import List, Dict, Any
from ..parser.csv_loader import CSVLoader
from ..models.event import Event
from ..models.activity import Activity, EventActivityMapping
from ..models.pattern import MethodRecommendation, explain_missing_method, object_type_for
from ..inference.event_grouper import EventGrouper, LLMGroupRefiner
from ..inference.activity_inferrer import ActivityInferrer
from ..mapping.event_activity_mapper import EventActivityMapper
from ..matching.pattern_matcher import environment_evidence, richest_environment
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
                    "reasoning": a.reasoning,
                    "rule_checks": a.rule_checks,
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
        lines = ["=== RPA UI Log Analyzer Results ==="]
        model = self.statistics.get("llm_model")
        if model:
            note = " (backup model; the main model was unavailable)" if self.statistics.get("llm_backup_used") else ""
            lines.append(f"Model: {model}{note}")
        lines += [
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
                f"  {i}. {rec.activity_name} -> {rec.method or 'no method'} ({rec.execution_environment})"
            )
            if rec.method_note:
                lines.append(f"       {rec.method_note}")

        return "\n".join(lines)


class DataPipeline:
    """Main orchestrator for the UI log analysis pipeline with pattern matching."""

    def __init__(self, csv_path: str, llm_client=None):
        """
        Initialize DataPipeline.

        The columns used for grouping and for detecting application switches are
        identified by the LLM when the log is loaded (see ``run``), exactly as in
        the web app, so there is no option to set them by hand.

        Args:
            csv_path: Path to CSV UI log file
            llm_client: LLM client used for column detection, group refinement
                and activity inference
        """
        self.csv_path = csv_path
        self.llm_client = llm_client

        from ..matching import PATTERNS

        self.loader = CSVLoader(llm_client)
        self.grouper = EventGrouper()
        self.refiner = LLMGroupRefiner(llm_client)
        self.inferrer = ActivityInferrer(llm_client, patterns=PATTERNS)
        self.mapper = EventActivityMapper(self.grouper, self.inferrer)
        self.formatter = RecommendationFormatter()

    def run(self) -> PipelineResult:
        """
        Run the complete data pipeline.

        Returns:
            PipelineResult with activities, mappings, and recommendations
        """
        events = self.loader.load(self.csv_path)

        if self.loader.detected_group_columns:
            self.grouper.group_attributes = self.loader.detected_group_columns
        if self.loader.detected_switch_columns:
            self.grouper.context_switch_attributes = self.loader.detected_switch_columns
        self.grouper.element_attributes = list(self.loader.detected_element_columns or [])

        # The refinement and naming prompts show the LLM the same application and
        # context columns the grouper used, so their decisions rest on log data.
        application_attributes = list(self.grouper.context_switch_attributes)
        context_attributes = [
            c for c in self.grouper.group_attributes if c not in application_attributes
        ]
        element_attributes = list(self.loader.detected_element_columns or [])
        self.refiner.application_attributes = application_attributes
        self.refiner.context_attributes = context_attributes
        self.refiner.element_attributes = element_attributes
        self.inferrer.application_attributes = application_attributes
        self.inferrer.context_attributes = context_attributes
        self.inferrer.element_attributes = element_attributes

        # Step 1: segmentation by software and data context (rules); step 2: the LLM
        # abstracts UI activities from the segments, dividing and combining them.
        # This mirrors the web pipeline. The refine call is non-deterministic, so
        # it runs once and the resulting groups are reused for inference,
        # recommendations, and statistics to keep group indices aligned.
        groups = self.grouper.group_events_with_context_switches(events)
        groups = self.refiner.refine(groups)

        mappings = self.mapper.map_groups(groups)
        activities = [m.activity for m in mappings]

        # Recommend for the full enriched activity sequence — including the
        # implicit "Find <element>" and "Switch Context" activities — so the CLI
        # matches the web pipeline rather than emitting main activities only.
        enriched = getattr(self.mapper, "enriched_activities", activities)
        recommendations = self._create_recommendations(
            enriched, groups, self.loader.detected_environment_columns
        )

        statistics = {
            "total_events": len(events),
            "total_groups": len(mappings),
            "avg_events_per_group": len(events) / len(mappings) if mappings else 0,
            "avg_confidence": sum(m.confidence for m in mappings) / len(mappings)
            if mappings
            else 0,
            "grouper_stats": self.grouper.get_group_summary(
                [g.events for g in groups]
            ),
            "mapping_stats": self.mapper.get_mapping_summary(mappings),
            # What the LLM decided about the log's attributes (prompts P1 and P2), as step 1
            # of the web workspace shows it.
            "attribute_roles": {
                "activity_name": self.loader.detected_column,
                "application": application_attributes,
                "data_context": context_attributes,
                "element": element_attributes,
                "environment": self.loader.detected_environment_columns,
            },
            # Which model produced this result: the first task may have switched to the
            # backup model, and every later step of the run stayed on it.
            "llm_model": getattr(self.llm_client, "model", None),
            "llm_backup_used": bool(getattr(self.llm_client, "used_backup", False)),
        }

        return PipelineResult(
            activities=activities,
            mappings=mappings,
            recommendations=recommendations,
            statistics=statistics,
        )

    def _create_recommendations(
        self,
        activities: List[Activity],
        groups: List[Any],
        environment_columns: Dict[str, List[str]] = None,
    ) -> List[MethodRecommendation]:
        """Create one (prioritised) method recommendation per inferred activity.

        The execution environment is decided from the indicator columns the LLM
        identified for each environment when the log was loaded.

        Operates on the full enriched activity sequence (main + implicit Find /
        Switch-Context activities), looking up each activity's source group by
        ``group_index``. Mirrors the web pipeline's step 4/6 logic.
        """
        from ..matching import PATTERNS, PatternMatcher

        recommendations = []
        matcher = PatternMatcher(PATTERNS)

        for activity in activities:
            group_idx = activity.group_index
            group = groups[group_idx] if 0 <= group_idx < len(groups) else None
            events = group.events if group else []
            evidence = environment_evidence(events, environment_columns)
            context, deciding = richest_environment(evidence)

            # Switching between applications, windows or browser tabs is an operation of
            # the desktop, so a Switch Context activity always takes the desktop
            # environment (step 6 of the approach).
            is_context_switch = activity.activity_type == "context_switch"
            if is_context_switch:
                context, deciding, evidence = "desktop", {}, None
            method_environment = context

            # The pattern is matched by name only. If it has no variant for the
            # environment, the pattern is kept and the method note says why.
            pattern = matcher.match(activity)
            methods = pattern.get_methods_for_context(method_environment) if pattern else []
            method = methods[0] if methods else None

            event_indices = [e.row_index for e in events if e.row_index is not None]

            context_switch_from = group.previous_app if (is_context_switch and group) else None
            context_switch_to = group.current_app if (is_context_switch and group) else None

            # Action and Object come from the canonical Pattern matched via the
            # LLM-assigned pattern name — mirrors the web pipeline (step 3/6).
            # No pattern match means no action/object, rather than a heuristic guess.
            recommendation = MethodRecommendation(
                activity_name=activity.name,
                activity_action=pattern.action if pattern else None,
                activity_object=object_type_for(pattern, method_environment),
                events=event_indices,
                execution_environment=context,
                pattern=pattern,
                method=method,
                methods=methods,
                method_category=pattern.category if pattern else None,
                confidence=activity.confidence,
                context_attributes_used=list(deciding) or None,
                context_switch=is_context_switch,
                context_switch_from=context_switch_from,
                context_switch_to=context_switch_to,
                method_note=explain_missing_method(pattern, method_environment),
                target=getattr(activity, "target", None),
                environment_evidence=evidence,
                method_variants=pattern.describe_methods(method_environment) if pattern else [],
            )
            recommendations.append(recommendation)

        return recommendations
