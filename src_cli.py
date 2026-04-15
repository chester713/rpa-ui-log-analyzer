"""CLI entry point for RPA UI Log Analyzer."""

import argparse
import json
import sys
from pathlib import Path
from src.pipeline.data_pipeline import DataPipeline


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="RPA UI Log Analyzer - Activity Inference from UI Logs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src_cli.py sample.csv
  python src_cli.py sample.csv --output results.json
  python src_cli.py sample.csv --verbose
        """,
    )
    parser.add_argument("csv_file", help="Path to CSV UI log file")
    parser.add_argument("--output", "-o", help="Output file path (JSON)")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed output"
    )
    parser.add_argument(
        "--group-attr", nargs="+", help="Custom attributes for event grouping"
    )

    args = parser.parse_args()

    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"Error: File not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    try:
        pipeline = DataPipeline(
            csv_path=str(csv_path), group_attributes=args.group_attr
        )
        result = pipeline.run()

        if args.output:
            result.to_json(args.output)
            print(f"Results written to: {args.output}")
        else:
            print(result.summary())

        if args.verbose:
            print("\n=== Detailed Results ===")
            for i, mapping in enumerate(result.mappings, 1):
                print(f"\n--- Activity {i} ---")
                print(f"  Name: {mapping.activity.name}")
                print(f"  Confidence: {mapping.confidence:.2f}")
                print(f"  Evidence: {mapping.activity.evidence}")
                print(f"  Events: {len(mapping.events)}")
                print(
                    f"  Attribute Breakdown: {mapping.attribute_breakdown.get('shared_attributes', [])}"
                )

            print("\n=== Method Recommendations ===")
            for i, rec in enumerate(result.recommendations, 1):
                print(f"\n--- Recommendation {i} ---")
                print(f"  Activity: {rec.activity_name}")
                print(f"  Events: {rec.events}")
                print(f"  Environment: {rec.execution_environment}")
                print(f"  Pattern: {rec.pattern.name if rec.pattern else 'None'}")
                print(f"  Method: {rec.method or 'None'}")
                print(f"  Category: {rec.method_category or 'None'}")

        sys.exit(0)

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
