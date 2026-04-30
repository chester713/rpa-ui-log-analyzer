# RPA UI Log Analyzer

An AI-powered recommendation system that analyzes UI interaction logs (CSV format) and suggests appropriate RPA automation methods based on a library of 13 UI interaction patterns.

Upload a UI event log and the tool infers what the user was doing at each step, matches each inferred activity to an RPA pattern, and recommends the most appropriate automation method (DOM manipulation, UI Automation, hardware simulation, etc.) broken down by execution environment.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Web app (recommended)
python app.py
# Open http://localhost:5000

# CLI mode
python src_cli.py sample.csv
```

## Recommendation Pipeline

The tool runs each log through six sequential steps:

| # | Step | How |
|---|------|-----|
| 1 | **Event Grouping** | Consecutive events sharing `app`, `webpage`, `url`, or `element_id` are merged into one activity group. An `app` / `application` change triggers a context-switch boundary. | Rule-based |
| 2 | **Activity Inference** | Each group is sent to an LLM (batched × 5, up to 5 parallel threads). Returns an activity name, the best-matching pattern, context-switch detection, and whether a prerequisite Find step is needed. | LLM |
| 3 | **Action / Object Extraction** | The inferred name is parsed into Action + Object and normalised to the AOMC pattern vocabulary (e.g. click/press/tap → *Activate*; type/paste/fill → *Write*). If the LLM provided a pattern name, that is matched directly. | Hybrid |
| 4 | **Pattern Matching** | The action/object pair is looked up in the 13-pattern library. The LLM-supplied pattern name is tried first; rule-based normalisation is the fallback. | Hybrid |
| 5 | **Context Identification** | Event attributes are scanned in priority order — HTML attributes → **web**; app/workbook attributes → **desktop**; coordinate attributes → **screen**. | Rule-based |
| 6 | **Method Recommendation** | The matched pattern's method field is sliced for the identified environment (e.g. Write Element + web → *HTML DOM manipulation*). | Rule-based |

Two implicit activities are also inserted automatically:

- **Prerequisite Find Element** — inserted before any activity that targets a specific UI element, reflecting the bot's requirement to locate the element first.
- **Context Switch** — inserted at any application boundary, explicitly representing the environment transition.

## Pattern Library

Thirteen patterns across three categories:

| Category | Patterns |
|----------|----------|
| **Extraction** | Find Element, Read Element, Observe |
| **Modification** | Write Element, Delete Element, Disable Element |
| **Control** | Open, Activate, Hover, Switch Context, Scroll, Focus, Refresh |

Each pattern defines supported execution environments and one automation method per environment:

| Environment | Detection signal | Extraction method | Modification / Control method |
|-------------|-----------------|-------------------|-------------------------------|
| **Web** | `xpath`, `tag_name`, `browser_url`, `webpage` | HTML DOM parsing | HTML DOM manipulation |
| **Desktop** | `application`, `app`, `workbook`, `worksheet` | UI Automation tree parsing | UI Automation manipulation |
| **Screen** | `x`, `y`, `mouse_x`, `mouse_y` | Visual recognition | Hardware simulation |

## Web UI

The web interface (`python app.py`, port 5000) provides a guided five-page flow:

1. **Welcome** (`/`) — overview of the recommendation approach and pipeline.
2. **Upload** (`/upload`) — CSV file upload.
3. **Column Selection** (`/select-column`) — LLM automatically detects the event column; user can override.
4. **Guided Analysis** (`/workspace/<id>`) — step-by-step walkthrough of all six pipeline stages with the data produced at each step and the logic behind each decision.
5. **Results** (`/results/<id>`) — full recommendation table with pattern matches, methods, confidence scores, LLM evidence, and a Directly-Follows Graph (DFG) of the activity sequence.
6. **History** (`/history`) — past analyses stored in `data/history.json`.

### LLM Configuration

Go to **Settings** (`/settings`) or edit `config/llm_config.json`:

```json
{
  "provider": "puter",
  "endpoint": "",
  "api_key": "",
  "model": "gpt-4o-mini"
}
```

- `provider: "puter"` — uses the [Puter.ai](https://puter.com) free tier (no API key required, `gpt-4o-mini`).
- `provider: "custom"` — uses any OpenAI-compatible endpoint; set `endpoint`, `api_key`, and `model`.

If no config file exists the tool runs without an LLM and falls back to keyword-based rule inference.

## CLI Usage

```bash
# Basic — prints a summary table to stdout
python src_cli.py sample.csv

# Write JSON results to a file
python src_cli.py sample.csv --output results.json

# Verbose — prints per-activity detail
python src_cli.py sample.csv --verbose

# Override grouping attributes
python src_cli.py sample.csv --group-attr app webpage element_id
```

## Project Structure

```
app.py                 # Flask web application
src_cli.py             # CLI entry point

src/
├── parser/            # CSV loading, BOM handling, LLM-powered column detection
├── models/            # Event, Activity, Pattern, MethodRecommendation data classes
├── inference/         # EventGrouper (rule-based), ActivityInferrer (LLM)
├── mapping/           # EventActivityMapper — wires grouper and inferrer together
├── matching/          # PatternLoader, PatternMatcher, pattern library wiring
├── process_mining/    # Directly-Follows Graph (DFG) builder
├── pipeline/          # DataPipeline — end-to-end orchestrator used by CLI
└── llm/               # LLMClient supporting Puter and OpenAI-compatible providers

patterns/              # 13 pattern definition files (*.md)
templates/             # Jinja2 HTML templates for all web pages
config/                # llm_config.json (LLM settings), inference_rules.json
data/                  # history.json (analysis history), uploads/ (temp files)
tests/                 # pytest test suite
```

## Requirements

- Python 3.10+
- `flask>=2.0.0` — web application
- `requests>=2.28.0` — LLM API client
- `pm4py>=2.7.0` — process mining / DFG generation

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
