# RPA UI Log Analyzer

An AI-powered recommendation system that analyzes UI interaction logs (CSV format) and suggests appropriate RPA automation methods based on a library of 13 UI interaction patterns.

Upload a UI event log and the tool infers what the user was doing at each step, matches each inferred activity to an RPA pattern, and recommends the most appropriate automation method (DOM manipulation, UI Automation, hardware simulation, etc.) broken down by execution environment.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure an LLM (required — see "LLM Configuration" below)
cp config/llm_config.example.json config/llm_config.json
# then edit config/llm_config.json and add your API key

# Web app (recommended)
python app.py
# Open http://localhost:5000

# CLI mode
python src_cli.py sample.csv
```

> **An LLM is required.** Activity inference is performed entirely by the LLM — there is no keyword/rule-based fallback. If no key is configured, the tool surfaces an error rather than degrading to heuristics.

## Recommendation Pipeline

The pipeline implements a two-stage recommendation approach: **task interpretation** followed by **method recommendation**.

In task interpretation, consecutive UI events are grouped into interaction segments based on their collective intent — events that together constitute a single coherent interaction belong in the same group. The resulting group is then named as an activity using the pattern vocabulary. In method recommendation, the matched pattern and the detected execution environment together determine which automation method to recommend, following a priority order: content-level (web) → accessibility-level (desktop) → visual/hardware simulation (screen).

The tool runs each log through six sequential steps:

| # | Step | How |
|---|------|-----|
| 1 | **Event Grouping** | Consecutive events are grouped into interaction segments by collective intent. Shared attributes (`app`, `webpage`, `url`, `element_id`) serve as supporting evidence; a change in `app` / `application` triggers a context-switch boundary. | Rule-based |
| 2 | **Activity Naming** | Groups are sent to an LLM in batches of 5 (processed sequentially to respect rate limits) to be named as activities. The LLM identifies each group's collective intent and assigns a name aligned with the pattern vocabulary. It also detects context switches and whether a prerequisite Find step is needed. | LLM |
| 3 | **Action / Object Extraction** | The Action and Object are taken from the pattern the LLM assigned in step 2 — each pattern carries a canonical Action/Object pair in the AOMC (Action-Object-Method-Context) vocabulary. Log-level verbs (click/press/tap, type/paste/fill, etc.) are resolved to that shared vocabulary by the LLM, not by a hardcoded map. | LLM |
| 4 | **Pattern Matching** | The activity is matched to a pattern in the RPA UI Interaction Pattern Library via the LLM-assigned pattern name. | LLM |
| 5 | **Context Identification** | Event attributes are scanned in priority order — HTML attributes → **web**; app/workbook attributes → **desktop**; coordinate attributes → **screen**. | Rule-based |
| 6 | **Method Recommendation** | The matched pattern's method field is resolved for the identified environment (e.g. Write Element + web → *HTML DOM manipulation*). | Rule-based |

Two implicit activities are also inserted automatically:

- **Prerequisite Find Element** — inserted before any activity that targets a specific UI element, reflecting the bot's requirement to locate the element first.
- **Context Switch** — inserted at any application boundary, explicitly representing the environment transition.

## RPA UI Interaction Pattern Library

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

The web interface (`python app.py`, port 5000) provides a guided six-page flow:

1. **Welcome** (`/`) — overview of the recommendation approach and pipeline.
2. **Upload** (`/upload`) — CSV file upload.
3. **Column Selection** (`/select-column`) — LLM automatically detects the event column; user can override.
4. **Guided Analysis** (`/workspace/<id>`) — step-by-step walkthrough of all six pipeline stages with the data produced at each step and the logic behind each decision.
5. **Results** (`/results/<id>`) — full recommendation table with pattern matches, methods, confidence scores, LLM evidence, and a Directly-Follows Graph (DFG) of the activity sequence.
6. **History** (`/history`) — past analyses stored in `data/history.json`.

### LLM Configuration

The tool needs an LLM to run. `config/llm_config.json` is **not** committed (it may hold a private key); copy the template and fill it in:

```bash
cp config/llm_config.example.json config/llm_config.json
```

Then edit it, or use **Settings** (`/settings`) in the web UI:

```json
{
  "provider": "custom",
  "endpoint": "https://api.openai.com/v1/chat/completions",
  "api_key": "YOUR_API_KEY",
  "model": "gpt-4o-mini"
}
```

- `provider: "custom"` (recommended) — any OpenAI-compatible endpoint. Set `endpoint`, `api_key`, and `model`. Works with OpenAI, Groq, OpenRouter, a local server, etc.
- `provider: "puter"` — experimental no-key path via the [Puter.ai](https://puter.com) endpoint; reliability is not guaranteed.

There is **no rule-based fallback**: if the configured LLM is missing or fails, the tool reports the error rather than producing degraded results. This is deliberate — the prototype is meant to reflect the LLM-driven approach directly.

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

## Known Limitations

- **Attribute-based grouping approximates intent-based grouping** — Ideally, events are grouped by their collective intent, with attributes serving as supporting evidence. In this prototype, grouping is driven by shared attribute values (`app`, `webpage`, `url`, `element_id`) as a tractable heuristic. This approximation works well in most logs because events sharing intent typically share attributes, but it can over-group events with different intents that happen to share an attribute, or mis-group edge cases where intent spans an attribute boundary.

- **Attribute-less sandwiched events** — Some loggers do not record target-object attributes (e.g. element ID, URL) for certain events such as `Paste` or keyboard shortcuts. If such an event has *no* grouping attributes at all, the grouper treats it as a context-switch boundary and splits the group incorrectly, rather than absorbing it into the surrounding group. In practice this only affects logs where the intermediate event carries zero attributes; most loggers retain at least the application name or URL, which is sufficient for correct grouping.

- **SME task interpretation is simulated by LLM** — The recommendation approach as described requires a Subject Matter Expert (SME) to map interaction segments to meaningful business tasks. In this prototype that step is approximated by LLM inference. The LLM may misinterpret activities in unfamiliar domains or where log attributes are sparse.

- **LLM is mandatory; output quality depends on it** — There is no keyword/heuristic fallback. Activity naming, action/object extraction, and pattern matching are all LLM-driven, so results vary with the model chosen and the clarity of the log. Robustness is pursued by tightening the prompts rather than by adding rule-based safety nets.

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
config/                # llm_config.example.json (template; copy to llm_config.json),
                       # inference_rules.json
data/                  # runtime artifacts (git-ignored):
                       #   history.json        — analysis history
                       #   uploads/            — uploaded CSVs
                       #   progressive/<id>/   — cached per-step pipeline output
tests/                 # pytest test suite
```

> Everything under `data/` is generated at runtime and is git-ignored; the real `config/llm_config.json` is git-ignored too. Only `config/llm_config.example.json` is committed.

## Requirements

- Python 3.10+
- `flask>=2.0.0` — web application
- `requests>=2.28.0` — LLM API client
- `pm4py>=2.7.0` — process mining / DFG generation
- `python-dotenv>=1.0.0` — loads environment variables from `.env`
- An OpenAI-compatible LLM API key (see [LLM Configuration](#llm-configuration))

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
