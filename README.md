# RPA UI Log Analyzer

An AI-powered recommendation system that analyzes UI interaction logs (CSV format) and suggests appropriate RPA automation methods based on a library of 13 UI interaction patterns.

Upload a UI event log and the tool infers what the user was doing at each step, matches each inferred activity to an RPA pattern, and recommends a prioritised list of applicable automation methods (DOM manipulation, UI Automation, hardware simulation, etc.) for the activity's execution environment.

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

The pipeline implements a two-stage recommendation approach: **UI activity inference** followed by **method recommendation**.

In UI activity inference, consecutive UI events are grouped by their collective intent — events that together constitute a single coherent interaction belong in the same group — and the UI activity that produced each group is inferred and named using the pattern vocabulary. Business tasks (what the process is for) are out of scope: the approach works at the level of UI activities and actions. In method recommendation, the matched pattern and the detected execution environment together determine a prioritised list of applicable automation methods, ordered content-level (DOM) → accessibility-level (UI Automation) → visual/input-level (visual recognition, hardware simulation).

The tool runs each log through six sequential steps:

| # | Step | How |
|---|------|-----|
| 1 | **Event Grouping** | An LLM reads the CSV header and sample rows to identify which columns carry context — the application, webpage, URL, element, etc. (column names differ between loggers, so none are hardcoded). Consecutive events that share a value in one of those columns are pre-segmented into candidate groups, and a change of the recorded application value closes the current group (a candidate boundary — an event with no application value is not treated as a change, and later events are compared with the last recorded application). An LLM second pass then turns the candidate groups into UI activities, in batches of 10 groups: it sees every event, numbered, with its target element, and returns runs of consecutive event numbers, one per UI activity. It may **divide** a group (clicking a text field, which focuses it, is a separate activity from pasting into it) and **combine** events of directly adjacent groups (a paste and the value-changed event it causes form one Write). Between adjacent groups it is shown the application-related attributes (then URL, window and element values) of both sides, carrying the last recorded application across a group that recorded none. | Rule-based + LLM |
| 2 | **Activity Naming** | Groups are sent to an LLM in batches of 5 (processed sequentially to respect rate limits). For each group the LLM returns a unique, context-specific activity name aligned with the pattern vocabulary, the name of the RPA pattern that fits (or `null` when no pattern fits — the activity is then reported as not covered by the collection), the concrete target element (or `null` for page-level actions), supporting evidence, and a confidence score. Implicit Switch context, Find and Focus activities are then inserted by fixed rules (see below). | LLM + Rule-based |
| 3 | **Action / Object Extraction** | The Action is read from the pattern the LLM assigned in step 2. The Object type follows from the execution environment — *HTML element* (web), *UI element* (desktop), *visual element* (screen) — except for Switch Context, which acts on a *Context*; the concrete target (e.g. *First Name field*) comes from step 2. No separate LLM call is made: log-level verbs (click/press/tap, type/paste/fill, etc.) were already resolved to the pattern vocabulary by the LLM when it named the activity. An unrecognised pattern name yields no pair rather than a guess. | Lookup |
| 4 | **Pattern Matching** | The pattern name assigned in step 2 is resolved (case-insensitively) against the RPA UI Interaction Pattern Library. Matching is by name only: whether the pattern can be carried out in the activity's execution environment is checked in step 6, so an activity keeps its pattern even when the pattern has no variant for that environment. If the name is missing or unknown, the activity is left without a pattern. No LLM call is made. | Lookup |
| 5 | **Context Identification** | When the log is loaded, the LLM identifies which columns indicate each environment — columns describing an HTML element or browser location → **web**; a native application's interface or document structure → **desktop**; raw screen coordinates → **screen** — by what the column describes, not its name. Each activity's environment is the highest-priority one (web > desktop > screen) for which one of its events recorded a value in such a column; otherwise *unknown*. | LLM (column roles, at load) + Rule-based |
| 6 | **Method Recommendation** | The matched pattern's applicable methods for the identified environment are listed in priority order, at most three (e.g. Write Element + web → *DOM manipulation*, *UI Automation manipulation*, *Hardware simulation*; + desktop → *UI Automation manipulation*, *Hardware simulation*; + screen → *Hardware simulation*). If the pattern has no applicable variant (e.g. Delete Element on screen) or the environment could not be determined, no method is recommended and the reason is shown instead. | Rule-based |

*Lookup* steps make no model call: they read what the LLM already decided in step 2. The LLM is called for four things only — suggesting the event column, identifying the column roles (application, grouping, environment and element columns, in one call), forming UI activities from the candidate groups, and naming activities.

Implicit activities are inserted by **fixed rules**, applied after activity naming in this order to each activity, each rule seeing the activities already inserted:

1. **Switch Context** — the activity is recorded in a different application from the last application recorded before it ("Switch context from A to B"). A missing application value is no evidence, and a URL change within one application is not a switch.
2. **Find Element** — the activity's pattern acts on a specific element (Read Element, Observe, Write Element, Delete Element, Disable Element, Activate, Focus, Hover), unless the preceding activity already targets the same element (same value in an element column, else the same target name).
3. **Focus** — the activity writes into an element (Write Element) and the preceding activity does not focus that element.

So an element is found, then focused, then written to, and one Find serves both the Focus and the Write.

## RPA UI Interaction Pattern Library

Thirteen patterns across three categories:

| Category | Patterns |
|----------|----------|
| **Extraction** | Find Element, Read Element, Observe |
| **Modification** | Write Element, Delete Element, Disable Element |
| **Control** | Open, Activate, Hover, Switch Context, Scroll, Focus, Refresh |

Each pattern defines the execution environments it supports and, for each, an automation method. Applicability is cumulative: a **web** environment can use every method (DOM, UI Automation, visual recognition, hardware simulation); a **desktop** environment can use UI Automation, visual recognition and hardware simulation; a **screen** environment can use only visual recognition and hardware simulation. The tool recommends the applicable methods the pattern defines as a prioritised list — content-level first, then accessibility-level, then visual/input-level — so the list holds at most three methods. The top-priority method per environment is:

| Environment | Detection signal (examples) | Extraction method (top priority) | Modification / Control method (top priority) |
|-------------|-----------------|-------------------|-------------------------------|
| **Web** | `xpath`, `tag_name`, `browser_url`, `webpage`, `url` | HTML DOM parsing | HTML DOM manipulation |
| **Desktop** | `application`, `app`, `window_title`, `workbook`, `worksheet` | UI Automation tree parsing | UI Automation manipulation |
| **Screen** | `x`, `y`, `mouse_x`, `mouse_y` | Visual recognition | Hardware simulation |

The exact wording of a method varies slightly between pattern files, and the detection signals are examples: which columns signal each environment is decided by the LLM for each log (`DEFAULT_ENVIRONMENT_COLUMNS` in `src/matching/pattern_matcher.py` is used only to replay analyses stored before this was added). Not every pattern covers every environment: **Delete Element** has no screen variant, **Switch Context** is desktop-only, and **Hover** has no UI Automation variant (DOM manipulation then hardware simulation on web, hardware simulation on desktop and screen). When a pattern does not support the detected environment, the activity keeps its pattern but gets no method, and the reason is shown — for example *No method for the screen environment: Delete Element has no screen variant (an element cannot be deleted from an image).* The reason comes from an optional `## Unsupported Environments` section in the pattern file (one `- screen: …` line per environment); without it, the message just states that the variant is missing.

## Web UI

The web interface (`python app.py`, port 5001) provides a guided six-page flow:

1. **Welcome** (`/`) — overview of the recommendation approach and pipeline.
2. **Upload** (`/upload`) — CSV file upload (`.csv`, up to 16 MB).
3. **Column Selection** (`/select-column`) — the LLM suggests the event column; click any column header to override it.
4. **Guided Analysis** (`/workspace/<id>`) — step-by-step walkthrough of all six pipeline stages with the data produced at each step and the logic behind each decision.
5. **Results** (`/results/<id>`) — three linked panels plus a graph:
   - **Original Log** — every row of the uploaded CSV (values in columns whose names look sensitive — password, secret, token, API key — are shown as `[REDACTED]`); click a row to inspect its inferred activity.
   - **Inferred Activities** — the activity sequence, labelled *Recorded*, *Prerequisite* (Find) or *Switch* (context switch); click one to see its details.
   - **Pattern & Method** — the matched pattern, the prioritised list of recommended methods (or the reason there is none), the context attributes that decided the environment, and the LLM's confidence score and evidence for the activity (implicit Find / Switch steps are inserted from the LLM's flags and show *n/a*). The **method dropdown** defaults to the top-priority method and lets you override it (Extraction: DOM parsing, UI Automation tree parsing, visual recognition, hardware simulation; Modification: DOM manipulation, UI Automation manipulation, hardware simulation); the override is kept in the page only and is reflected in the export.
   - **Direct-Follow Graph (DFG)** — the activity sequence as a directly-follows graph with zoom controls; clicking a node selects the matching activity and log rows.
   - **Export CSV** — downloads the original log with five columns appended: `inferred_activity`, `execution_context`, `matched_pattern`, `recommended_method` (the top-priority method, or the override) and `prioritised_methods` (the full list, `>`-separated).
6. **History** (`/history`) — past analyses stored in `data/history.json`, each linking to its workspace and results.

### LLM Configuration

#### LLM used

The LLM is called for four things — suggesting the event column, identifying the column roles (application and grouping columns, and the columns that indicate each execution environment), refining event groups, and naming activities (which also assigns each activity's pattern, prerequisite Find step, context-switch flag, evidence and confidence). Action/object extraction, pattern matching, the per-activity environment decision and method recommendation make no model call. All four LLM tasks use this model by default:

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

- **Context-based pre-segmentation is only a starting point** — Candidate groups are formed from shared values in the context columns; the LLM then divides and combines them by intent. Events on either side of a batch edge (every 10 candidate groups) are never combined.

- **Events without an application value** — Some loggers leave the application column empty for certain events such as `Paste` or keyboard shortcuts. A missing value is treated as "no information", never as a different application: the event stays with its neighbours when it shares a URL, element ID or another grouping value with them, and later events are compared with the last recorded application. An event that shares nothing — for instance one with no attributes at all — becomes a group of its own, and only the LLM refinement pass can merge it back.

- **The LLM decides the UI activities; switches follow the recorded application** — The code does not override how the LLM divides and combines events; it only checks that each UI activity is a run of consecutive events and that every event is covered once. Context switches are detected from the application column only: a switch between windows or browser tabs of the same application is not detected unless the log records it as an event of its own.

- **SME judgement is simulated by LLM** — The recommendation approach as described relies on a Subject Matter Expert (SME) to judge the collective intent of consecutive events and then to normalise the resulting UI activities to the pattern vocabulary. In this prototype that judgement is approximated by LLM inference; implicit activities follow fixed rules. The LLM may misinterpret activities in unfamiliar domains or where log attributes are sparse.

- **LLM is mandatory; output quality depends on it** — There is no keyword/heuristic fallback. Column identification, forming UI activities, activity naming and pattern assignment are LLM-driven (action/object extraction and pattern matching only look up the pattern the LLM assigned; implicit activities follow fixed rules), so results vary with the model and the clarity of the log. Robustness is pursued by tightening the prompts rather than by adding rule-based safety nets.

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
