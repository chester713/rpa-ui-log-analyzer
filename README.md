# RPA UI Log Analyzer

An AI-powered recommendation system that analyzes UI interaction logs (CSV format) and suggests appropriate RPA automation methods based on a library of 13 UI interaction patterns.

Upload a UI event log and the tool infers what the user was doing at each step, matches each inferred activity to an RPA pattern, and recommends the most appropriate automation method (DOM manipulation, UI Automation, hardware simulation, etc.) broken down by execution environment.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Provide the API key for the default LLM (required — see "LLM Configuration" below)
export GEMINI_API_KEY="your-key"      # PowerShell: $env:GEMINI_API_KEY = "your-key"

# Web app (recommended)
python app.py
# Open http://localhost:5001

# CLI mode
python src_cli.py sample.csv
```

> **An LLM is required.** The prototype uses a default hosted LLM (Gemini), so users never choose a model or enter a key in the UI — whoever runs the app supplies `GEMINI_API_KEY` once. Activity inference is performed by the LLM — there is no keyword/rule-based fallback. If the key is missing or the model fails, the tool surfaces an error rather than degrading to heuristics.

## Recommendation Pipeline

The pipeline implements a two-stage recommendation approach: **task interpretation** followed by **method recommendation**.

In task interpretation, consecutive UI events are grouped into interaction segments based on their collective intent — events that together constitute a single coherent interaction belong in the same group. The resulting group is then named as an activity using the pattern vocabulary. In method recommendation, the matched pattern and the detected execution environment together determine which automation method to recommend, following a priority order: content-level (web) → accessibility-level (desktop) → visual/hardware simulation (screen).

The tool runs each log through six sequential steps:

| # | Step | How |
|---|------|-----|
| 1 | **Event Grouping** | An LLM reads the CSV header and sample rows to identify which columns carry context — the application, webpage, URL, element, etc. (column names differ between loggers, so none are hardcoded). Consecutive events that share a value in one of those columns are pre-segmented into candidate groups, and a change of the recorded application value closes the current group (a candidate boundary — an event with no application value is not treated as a change, and later events are compared with the last recorded application). An LLM second pass then refines the candidate groups: for every pair of adjacent groups it is shown the application-related attributes (then URL, window and element values) of both sides — carrying the last recorded application across a group that recorded none — and makes the final decision to merge directly-adjacent groups that share one intent, in batches of 10 groups. | Rule-based + LLM |
| 2 | **Activity Naming** | Groups are sent to an LLM in batches of 5 (processed sequentially to respect rate limits). For each group the LLM returns a unique, context-specific activity name aligned with the pattern vocabulary, the name of the RPA pattern that fits, whether the group switches application/environment (judged against the most recently recorded application, URL and window, carried forward over groups that did not record them), whether a prerequisite Find step is needed (and its name), supporting evidence, and a confidence score. | LLM |
| 3 | **Action / Object Extraction** | The Action and Object are read from the pattern the LLM assigned in step 2 — each pattern carries a canonical Action/Object pair in the AOMC (Action-Object-Method-Context) vocabulary. No separate LLM call is made: log-level verbs (click/press/tap, type/paste/fill, etc.) were already resolved to the pattern vocabulary by the LLM when it named the activity. An unrecognised pattern name yields no pair rather than a guess. | Lookup |
| 4 | **Pattern Matching** | The pattern name assigned in step 2 is resolved (case-insensitively) against the RPA UI Interaction Pattern Library. Matching is by name only: whether the pattern can be carried out in the activity's execution environment is checked in step 6, so an activity keeps its pattern even when the pattern has no variant for that environment. If the name is missing or unknown, the activity is left without a pattern. No LLM call is made. | Lookup |
| 5 | **Context Identification** | Event attributes are scanned in priority order — HTML attributes → **web**; app/workbook attributes → **desktop**; coordinate attributes → **screen**. | Rule-based |
| 6 | **Method Recommendation** | The matched pattern's method for the identified environment is selected (e.g. Write Element + web → *DOM manipulation*; + desktop → *UI Automation manipulation*; + screen → *Hardware simulation*). If the pattern has no variant for the environment (e.g. Delete Element on screen) or the environment could not be determined, no method is recommended and the reason is shown instead. | Rule-based |

*Lookup* steps make no model call: they read what the LLM already decided in step 2. The LLM is called for four things only — suggesting the event column, identifying the context columns, refining groups, and naming activities.

Two implicit activities can also be inserted. Both are decided by the LLM during activity naming (step 2), not by fixed rules, so they can vary between runs and models:

- **Prerequisite Find Element** — the LLM flags activities that read from, write to, focus or activate a specific element (not page-level actions such as opening a URL, scrolling or refreshing) and names the element to locate. A "Find …" step is inserted immediately before such an activity, reflecting the bot's requirement to locate the element first.
- **Context Switch** — the LLM compares each group with the previous group's context (application, URL, window, workbook) and flags a switch when the user moves to a different application or execution environment (web / desktop / screen); a "Switch context from A to B" step is inserted before the group. Navigating to another page of the same site is not a switch.

## RPA UI Interaction Pattern Library

Thirteen patterns across three categories:

| Category | Patterns |
|----------|----------|
| **Extraction** | Find Element, Read Element, Observe |
| **Modification** | Write Element, Delete Element, Disable Element |
| **Control** | Open, Activate, Hover, Switch Context, Scroll, Focus, Refresh |

Each pattern defines the execution environments it supports and, for each, an automation method. Applicability is cumulative: a **web** environment can use every method (DOM, UI Automation, visual recognition, hardware simulation); a **desktop** environment can use UI Automation, visual recognition and hardware simulation; a **screen** environment can use only visual recognition and hardware simulation. The tool recommends the highest-fidelity method the pattern defines for the detected environment:

| Environment | Detection signal (examples) | Extraction method | Modification / Control method |
|-------------|-----------------|-------------------|-------------------------------|
| **Web** | `xpath`, `tag_name`, `browser_url`, `webpage`, `url` | HTML DOM parsing | HTML DOM manipulation |
| **Desktop** | `application`, `app`, `window_title`, `workbook`, `worksheet` | UI Automation tree parsing | UI Automation manipulation |
| **Screen** | `x`, `y`, `mouse_x`, `mouse_y` | Visual recognition | Hardware simulation |

The exact wording of a method varies slightly between pattern files, and the complete attribute lists are in `get_context_from_events` (`src/matching/pattern_matcher.py`). Not every pattern covers every environment: **Delete Element** has no screen variant, **Switch Context** is desktop-only, and **Hover** has no UI Automation variant (DOM manipulation on web, hardware simulation on desktop and screen). When a pattern does not support the detected environment, the activity keeps its pattern but gets no method, and the reason is shown — for example *No method for the screen environment: Delete Element has no screen variant (an element cannot be deleted from an image).* The reason comes from an optional `## Unsupported Environments` section in the pattern file (one `- screen: …` line per environment); without it, the message just states that the variant is missing.

## Web UI

The web interface (`python app.py`, port 5001) provides a guided six-page flow:

1. **Welcome** (`/`) — overview of the recommendation approach and pipeline.
2. **Upload** (`/upload`) — CSV file upload (`.csv`, up to 16 MB).
3. **Column Selection** (`/select-column`) — the LLM suggests the event column; click any column header to override it.
4. **Guided Analysis** (`/workspace/<id>`) — step-by-step walkthrough of all six pipeline stages with the data produced at each step and the logic behind each decision.
5. **Results** (`/results/<id>`) — three linked panels plus a graph:
   - **Original Log** — every row of the uploaded CSV (values in columns whose names look sensitive — password, secret, token, API key — are shown as `[REDACTED]`); click a row to inspect its inferred activity.
   - **Inferred Activities** — the activity sequence, labelled *Recorded*, *Prerequisite* (Find) or *Switch* (context switch); click one to see its details.
   - **Pattern & Method** — the matched pattern, the recommended method (or the reason there is none), the context attributes that decided the environment, and the LLM's confidence score and evidence for the activity (implicit Find / Switch steps are inserted from the LLM's flags and show *n/a*). The **method dropdown** lets you override the recommendation (Extraction: DOM parsing, UI Automation tree parsing, visual recognition, hardware simulation; Modification: DOM manipulation, UI Automation manipulation, hardware simulation); the override is kept in the page only and is reflected in the export.
   - **Direct-Follow Graph (DFG)** — the activity sequence as a directly-follows graph with zoom controls; clicking a node selects the matching activity and log rows.
   - **Export CSV** — downloads the original log with four columns appended: `inferred_activity`, `execution_context`, `matched_pattern` and `recommended_method` (including any override).
6. **History** (`/history`) — past analyses stored in `data/history.json`, each linking to its workspace and results.

### LLM Configuration

#### LLM used

The LLM is called for four things — suggesting the event column, identifying the context columns used for grouping, refining event groups, and naming activities (which also assigns each activity's pattern, prerequisite Find step, context-switch flag, evidence and confidence). Action/object extraction, pattern matching, context identification and method recommendation make no model call. All four LLM tasks use this model by default:

| Setting | Value |
|---------|-------|
| **Model** | `gemini-3.1-flash-lite` (Google Gemini) |
| **Endpoint** | `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` (Gemini's OpenAI-compatible API) |
| **API key** | `GEMINI_API_KEY` environment variable, or `api_key` in `config/llm_config.json` |
| **Temperature** | `0` |
| **Max output tokens** | `2000` per request |
| **Timeout / retries** | 30 s per request; up to 2 retries with exponential backoff on timeouts, connection errors, and HTTP 429 |

These defaults are defined in `src/llm/client.py` and mirrored in `config/llm_config.example.json`. Results from this prototype should be attributed to this model unless the configuration was overridden.

#### Configuration

No key is stored in the repository. The model is provided by the prototype, so end users never enter a key or choose a model (there is no settings page); whoever runs the app supplies the key once through the `GEMINI_API_KEY` environment variable. The web app also reads it from a git-ignored `.env` file (`GEMINI_API_KEY=...`); the CLI does not load `.env`, so export the variable in your shell.

Developers who need a different key, endpoint or model can create a git-ignored `config/llm_config.json` from the template:

```bash
cp config/llm_config.example.json config/llm_config.json
```

```json
{
  "provider": "custom",
  "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
  "api_key": "YOUR_API_KEY",
  "model": "gemini-3.1-flash-lite"
}
```

Any field left empty falls back to the default above. The client speaks the OpenAI chat-completions protocol, so `endpoint`, `api_key`, and `model` can be pointed at another compatible provider (OpenAI, Groq, OpenRouter, a local server), but `gemini-3.1-flash-lite` is the documented default. (The `provider` field is retained as `"custom"` for backward compatibility.)

There is **no rule-based fallback**: if the configured LLM is missing or fails, the tool reports the error rather than producing degraded results. This is deliberate — the prototype is meant to reflect the LLM-driven approach directly.

## CLI Usage

```bash
# Basic — prints a text summary (activities and recommended methods) to stdout
python src_cli.py sample.csv

# Write JSON results to a file (includes confidence and LLM evidence per activity)
python src_cli.py sample.csv --output results.json

# Verbose — prints per-activity detail, including confidence and LLM evidence
python src_cli.py sample.csv --verbose
```

The CLI runs the same pipeline as the web app. Grouping columns are identified by the LLM in both, so there is no option to set them by hand.

## Known Limitations

- **Attribute-based grouping approximates intent-based grouping** — Ideally, events are grouped by their collective intent, with attributes serving as supporting evidence. In this prototype, the LLM identifies which columns carry context (for example the application, webpage, URL or element — the names depend on the logger) and grouping is driven by shared values in those columns as a tractable heuristic. This approximation works well in most logs because events sharing intent typically share attributes, but it can over-group events with different intents that happen to share an attribute, or mis-group edge cases where intent spans an attribute boundary.

- **Events without an application value** — Some loggers leave the application column empty for certain events such as `Paste` or keyboard shortcuts. A missing value is treated as "no information", never as a different application: the event stays with its neighbours when it shares a URL, element ID or another grouping value with them, and later events are compared with the last recorded application. An event that shares nothing — for instance one with no attributes at all — becomes a group of its own, and only the LLM refinement pass can merge it back.

- **The LLM makes the final merge and switch decisions** — The refinement pass and activity naming are shown the log's application-related attributes as evidence (changed, same, or not recorded), but the code does not override their answers; it only checks that merged groups are adjacent. The model can therefore occasionally merge across a real application switch, keep apart groups that serve one intention, or miss a context switch. Groups are refined in batches of 10, so two groups on either side of a batch edge are never merged.

- **SME task interpretation is simulated by LLM** — The recommendation approach as described requires a Subject Matter Expert (SME) to map interaction segments to meaningful business tasks. In this prototype that step is approximated by LLM inference. The LLM may misinterpret activities in unfamiliar domains or where log attributes are sparse.

- **LLM is mandatory; output quality depends on it** — There is no keyword/heuristic fallback. Column identification, group refinement, activity naming and pattern assignment are LLM-driven (action/object extraction and pattern matching only look up the pattern the LLM assigned), so results vary with the model and the clarity of the log. Robustness is pursued by tightening the prompts rather than by adding rule-based safety nets.

## Project Structure

```
app.py                 # Flask web application
src_cli.py             # CLI entry point
sample.csv             # small example UI log

src/
├── parser/            # CSV loading, BOM and duplicate-header handling, LLM-powered detection of the event and context columns
├── models/            # Event, Activity, Pattern, MethodRecommendation data classes
├── inference/         # EventGrouper + LLMGroupRefiner (grouping), ActivityInferrer (LLM)
├── mapping/           # EventActivityMapper — wires grouper and inferrer together
├── matching/          # PatternLoader, PatternMatcher, RecommendationFormatter, pattern library wiring
├── process_mining/    # Directly-Follows Graph (DFG) builder
├── pipeline/          # DataPipeline — end-to-end orchestrator used by the CLI
├── web/               # Guided-analysis pipeline used by the web app (computes each stage on demand, caches results per analysis)
└── llm/               # LLMClient for OpenAI-compatible endpoints (default: Gemini)

patterns/              # 13 pattern definition files (*.md) — read at startup
skills/                # design notes on the pattern library and recommendation logic (not read by the code)
templates/             # Jinja2 HTML templates for all web pages
config/                # llm_config.example.json (template; copy to llm_config.json)
data/                  # runtime artifacts (git-ignored):
                       #   history.json        — analysis history
                       #   uploads/            — uploaded CSVs
                       #   progressive/<id>/   — cached per-step pipeline output
tests/                 # pytest test suite
```

> Everything under `data/` is generated at runtime and is git-ignored; the real `config/llm_config.json` is git-ignored too. Only `config/llm_config.example.json` is committed.

## Requirements

- Python 3.10+ (developed and tested on 3.12)
- `flask>=2.0.0` — web application
- `requests>=2.28.0` — LLM API client
- `pm4py>=2.7.0` — process mining / DFG generation (a built-in DFG builder is used if pm4py is unavailable)
- `python-dotenv>=1.0.0` — loads environment variables from `.env`
- A Gemini API key for the default model `gemini-3.1-flash-lite` (see [LLM Configuration](#llm-configuration))

## Tests

```bash
pytest
```

All tests run offline except `test_cli_output_json_contract`, which runs the real CLI end to end and therefore needs `GEMINI_API_KEY` and network access.

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
