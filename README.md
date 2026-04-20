# RPA UI Log Analyzer

An AI-powered recommendation system that analyzes UI interaction logs (CSV format) and suggests appropriate automation methods based on a defined set of RPA UI interaction patterns.

## Quick Start

```bash
# CLI mode
python src_cli.py <your_ui_log.csv>

# Web mode
python app.py
```

## Features

- **CSV Event Log Parsing** - Load and parse UI logs following the Abb & Rehse reference model
- **Event Grouping** - Group consecutive events by shared attributes (same app, webpage, element)
- **LLM-Powered Activity Inference** - Use AI to infer underlying activities from event sequences
- **Event-to-Activity Mapping** - Map events to activities with confidence scores and attribute breakdown

## Usage

```bash
# Basic usage
python src_cli.py sample.csv

# Output to JSON
python src_cli.py sample.csv --output results.json

# Verbose output
python src_cli.py sample.csv --verbose
```

## Requirements

- Python 3.x
- Dependencies in `requirements.txt`:
  - Flask (web portal)
  - requests (LLM API client)

## Project Structure

```
src/
├── parser/         # CSV loading and validation
├── models/         # Event and Activity data models
├── inference/      # Event grouping and activity inference
├── mapping/        # Event-to-activity mapping
└── pipeline/       # Main orchestrator

templates/          # Web UI pages
app.py              # Flask web application
patterns/           # Pattern definitions used by matcher
```

## License

Apache License 2.0 - see LICENSE file for details
