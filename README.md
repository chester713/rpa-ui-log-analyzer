# RPA UI Log Analyzer

An AI-powered recommendation system that analyzes UI interaction logs (CSV format) and suggests appropriate RPA automation methods based on a library of 13 UI interaction patterns.

Upload a UI log and the tool identifies the UI activities a bot has to perform, matches each to an RPA UI interaction pattern, and recommends a prioritised list of applicable automation methods (DOM manipulation, UI Automation, hardware simulation, etc.) for the activity's execution environment.

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

> **An LLM is required.** The prototype uses a default hosted LLM (Gemini), so users never choose a model or enter a key in the UI — whoever runs the app supplies `GEMINI_API_KEY` once. The LLM takes the place of the subject-matter expert in the approach — there is no keyword/rule-based fallback. If the key is missing or the model fails, the tool surfaces an error rather than degrading to heuristics.

## Recommendation Pipeline

The prototype implements the seven steps of the pattern-guided automation method recommendation approach, in two stages. Business tasks (what the process is for) are out of scope: the approach works at the level of UI activities.

**Stage 1 — UI activity identification**

| # | Step | How |
|---|------|-----|
| 1 | **Segment events by context** | When the log is loaded, an LLM (prompt P2) identifies the role of each attribute by what it describes, not its name: the application (software context), the further context such as webpage, window or worksheet (data context), the target element, and the attributes indicating each execution environment. The activity-name attribute is proposed by the LLM (prompt P1) and confirmed or changed by the analyst. Consecutive events then stay in one interaction segment while they share their software context; within it, a change of a data-context value (webpage, worksheet, UI element) starts a new segment. A value that was not recorded is no evidence of a change. | LLM (P1, P2) + rules |
| 2 | **Abstract higher-level UI activities** | In place of the SME, an LLM (prompt P3) receives the events of up to 10 segments, numbered and with their target elements, plus per-attribute evidence between adjacent segments (same / changed / not recorded), and returns runs of consecutive events, one per UI activity. It may divide a segment (a click that focuses a text field is a UI activity of its own) and combine adjacent segments (a paste and the field change it causes form one UI activity). The code only checks that runs are consecutive and cover every event once. | LLM |
| 3 | **Normalise UI activities** | In place of the SME, an LLM (prompt P4, batches of 5) returns for each UI activity its pattern — whose action is the normalised action — or `null` (not covered by the collection), its name in the form **action + object + context** (e.g. *Write First Name field on rpachallenge.com in Edge*, no input values), its target object and context, evidence and confidence. A pattern name outside the collection stops the analysis. | LLM |
| 4 | **Add implicit activities** | Fixed rules, in this order: **Switch context** (recorded in a different application from the last recorded one), **Find** (the activity acts on a target element — Read, Observe, Write, Delete, Disable, Activate, Hover, Focus, and Scroll / Refresh when they act on an element — unless the preceding activity targets the same element), **Focus** (before a Write unless the preceding activity focuses that element). | Rules |

**Stage 2 — Method recommendation**

| # | Step | How |
|---|------|-----|
| 5 | **Match patterns** | Each UI activity matches the pattern of its action (returned with the normalisation in step 3); implicit activities match the pattern they were inserted for. | Lookup |
| 6 | **Determine environment and object type** | The richest environment indicated by the attributes recorded for the activity's events (web > desktop > screen), or *unknown* if none is recorded. It determines the object type: HTML element, UI element or visual element. Find and Focus take the environment of the activity they precede; Switch Context always takes the desktop environment. | Rules |
| 7 | **Recommend prioritised methods** | The pattern's applicable methods, in order content-level (DOM) → accessibility-level (UI Automation) → visual recognition / hardware simulation, at most three. If there is none (e.g. Delete Element on screen, unknown environment, not covered), the reason is shown. | Rules |

The four LLM prompts are numbered P1 to P4 in the order they are used: **P1** proposes the activity-name attribute (at upload), **P2** identifies the roles of the attributes (when the analysis starts), **P3** abstracts the UI activities (step 2) and **P4** normalises them (step 3). The attribute-selection page and the workspace label them.

Every step's output is stored per analysis (`data/progressive/<id>/`), and the workspace and results pages are built from these files.

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

The web interface (`python app.py`, port 5001) provides a guided flow:

1. **Welcome** (`/`) — overview of the approach and its seven steps.
2. **Upload** (`/upload`) — CSV file upload (`.csv`, UTF-8, up to 16 MB). A file that is not UTF-8 is rejected with a hint to save it as "CSV UTF-8" (in Excel: Save As).
3. **Activity-name attribute** (`/select-column`) — the LLM proposes the attribute holding the activity names; click any attribute to change it (a prototype feature for when the LLM is wrong).
4. **Guided Analysis** (`/workspace/<id>`) — the seven steps of the approach, one page each, with the output of every step (including the rule-based segments of step 1) and the logic behind it. The steps in which the LLM decides also show **what it decided**: the role it gave every attribute of the log, with example values (P1, P2; step 1); what it did with each segment — kept it, divided it, or combined its events with the next segment's, together with the boundary the rules had drawn where it combined (P3; step 2); and, for each UI activity, the pattern it chose or that none fits, with its reasoning, evidence and confidence (P4; step 3, click a UI activity to see another). P1 to P3 return no reasons, so only their outcome is shown; nothing is explained after the fact. Step 3 runs the second LLM call when it is opened.
5. **Results** (`/results/<id>`):
   - **Recorded UI log** — every row of the uploaded CSV (values in attributes whose names look sensitive are shown as `[REDACTED]`); click an event to select its UI activity.
   - **Sequence of UI activities** — recorded and implicit (Switch, Find, Focus) activities in order, with the selected method.
   - **Pattern & Method** — pattern, object type and target, execution environment with the attributes that decided it, the prioritised methods with a **drop-down to select another method**, the reason when there is no method, and the LLM's confidence, reasoning and evidence for recorded activities.
   - **Directly-follows graph** — the sequence of UI activities; each occurrence is a node of its own, so the graph is a single path (UI interaction, not control flow).
   - **Export CSV** — the entire log, with each implicit activity inserted as a row before the UI activity it precedes, and columns `activity_no`, `activity_type`, `ui_activity`, `pattern`, `action`, `object_type`, `target`, `execution_environment`, `selected_method` (the recommendation or your selection), `prioritised_methods` and `method_note`.
6. **History** (`/history`) — past analyses, each linking to its workspace and results.

### LLM Configuration

#### LLM used

The LLM is called for four things — proposing the activity-name attribute (P1), identifying the roles of the other attributes (P2), abstracting UI activities (P3, step 2) and normalising them (P4, step 3). Steps 1 and 4 to 7 make no model call. All four LLM tasks use the main model below; the backup model is used only in the situation described under *Backup model*.

| Setting | Value |
|---------|-------|
| **Model** | `gemini-3.1-flash-lite` (Google Gemini) |
| **Backup model** | `gemini-3.5-flash-lite` (same endpoint and key) |
| **Endpoint** | `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions` (Gemini's OpenAI-compatible API) |
| **API key** | `GEMINI_API_KEY` environment variable, or `api_key` in `config/llm_config.json` |
| **Temperature** | `0` |
| **Max output tokens** | `2000` per request |
| **Timeout / retries** | 30 s per request; up to 2 retries with exponential backoff on timeouts, connection errors, HTTP 429 and temporary server errors (500, 502, 503, 504) |

These defaults are defined in `src/llm/client.py` and mirrored in `config/llm_config.example.json`. Results should be attributed to the model recorded with each analysis: the main model, unless the backup was used (see below). The model is shown in the results header, the workspace, the history table and the CLI output.

#### Backup model

The first task of every analysis — proposing the activity-name attribute (P1) when the log is uploaded — decides which model is used. If the main model cannot complete it because of a temporary provider problem (overload or server error, rate limit or quota, timeout — after the retries above), the task is retried once on the backup model. From then on, every later LLM task of that analysis (attribute roles P2, abstraction P3, normalisation P4) stays on the model that answered, so an analysis is never split across models. A failure in a later step is not switched; it is reported as an error. A wrong key or a rejected request does not trigger the switch (the backup would fail too), and there is no fallback to a rule-based method. The CLI JSON records the model in `statistics.llm_model` and `statistics.llm_backup_used`. Set `"backup_model": ""` in the config to switch the backup off.

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
  "model": "gemini-3.1-flash-lite",
  "backup_model": "gemini-3.5-flash-lite"
}
```

Any field you leave out falls back to the default above (an empty `"backup_model"` switches the backup off). The client speaks the OpenAI chat-completions protocol, so `endpoint`, `api_key`, and `model` can be pointed at another compatible provider (OpenAI, Groq, OpenRouter, a local server), but `gemini-3.1-flash-lite` is the documented default. (The `provider` field is retained as `"custom"` for backward compatibility.)

There is **no rule-based fallback**: if the configured LLM is missing or fails, the tool reports the error rather than producing degraded results. This is deliberate — the prototype is meant to reflect the LLM-driven approach directly. The web pages and the CLI state the cause in plain language, including the provider's own explanation — for example an overloaded model (HTTP 503, usually temporary), a quota limit (429) or a rejected key (401/403); the full provider response is written to the server log.

## CLI Usage

```bash
# Basic — prints a text summary (activities and recommended methods) to stdout
python src_cli.py sample.csv

# Write JSON results to a file (the confidence, evidence and reasoning of each activity, and under
# statistics.attribute_roles the roles the LLM gave the log's attributes)
python src_cli.py sample.csv --output results.json

# Verbose — prints the attribute roles and per-activity detail, including confidence, reasoning and LLM evidence
python src_cli.py sample.csv --verbose
```

The CLI runs the same pipeline as the web app. Grouping columns are identified by the LLM in both, so there is no option to set them by hand.

## Known Limitations

- **Segments are a starting point** — Step 1 segments by software and data context; the LLM then divides and combines the segments by intent. Segments are sent to the LLM in batches of 10, so events on either side of a batch boundary are never combined into one UI activity.

- **Values that were not recorded** — Some loggers leave attributes empty for events such as `Paste`. A missing value is treated as "no information", never as a change: the event stays in the current segment, and later events are compared with the last recorded value.

- **Same element without element attributes** — Whether two activities act on the same element (for the Find and Focus rules) is decided from the element attributes the events record; if the log records none, the target object and context named by the LLM are compared, and differently phrased names can produce an extra Find.

- **The LLM decides the UI activities; switches follow the recorded application** — The code does not override how the LLM divides and combines events; it only checks that each UI activity is a run of consecutive events and that every event is covered once. Context switches are detected from the application column only: a switch between windows or browser tabs of the same application is not detected unless the log records it as an event of its own.

- **Coverage is bounded by the pattern collection** — An action no pattern covers is reported as not covered: it keeps no pattern and gets no method, rather than being assigned to the closest pattern. The collection has no Close pattern, for instance, so closing a window or workbook is not matched. The LLM is told never to force a pattern, but it can occasionally still name such an action after a pattern that merely resembles it (a window-closing event named as a deletion). Extending the collection — a new file in `patterns/` — is how to cover more actions; the approach itself does not change.

- **SME judgement is simulated by LLM** — The recommendation approach as described relies on a Subject Matter Expert (SME) to judge the collective intent of consecutive events and then to normalise the resulting UI activities to the pattern vocabulary. In this prototype that judgement is approximated by an LLM; implicit activities follow fixed rules. The LLM may misinterpret activities in unfamiliar domains or where log attributes are sparse.

- **LLM is mandatory; output quality depends on it** — There is no keyword/heuristic fallback. Attribute roles, abstraction (step 2) and normalisation (step 3) are LLM-driven (pattern matching only looks up the pattern returned with the normalisation; segmentation, implicit activities, environment and methods follow fixed rules), so results vary with the model and the clarity of the log. Robustness is pursued by tightening the prompts rather than by adding rule-based safety nets.

## Project Structure

```
app.py                 # Flask web application
src_cli.py             # CLI entry point
sample.csv             # small example UI log

src/
├── parser/            # CSV loading, BOM and duplicate-header handling, LLM-powered detection of the event and context columns
├── models/            # Event, Activity, Pattern, MethodRecommendation data classes
├── inference/         # EventGrouper (step 1), LLMGroupRefiner (step 2), ActivityInferrer (step 3) and the implicit-activity rules (step 4)
├── mapping/           # EventActivityMapper — wires grouper and inferrer together
├── matching/          # PatternLoader, PatternMatcher, RecommendationFormatter, pattern library wiring
├── pipeline/          # DataPipeline — end-to-end orchestrator used by the CLI
├── web/               # The seven steps for the web app; stores each step's output per analysis and builds the pages from it
└── llm/               # LLMClient for OpenAI-compatible endpoints (default: Gemini)

patterns/              # 13 pattern definition files (*.md) — read at startup
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
- `python-dotenv>=1.0.0` — loads environment variables from `.env`
- A Gemini API key for the default model `gemini-3.1-flash-lite` (see [LLM Configuration](#llm-configuration))

## Tests

```bash
pytest
```

All tests run offline except `test_cli_output_json_contract`, which runs the real CLI end to end and therefore needs `GEMINI_API_KEY` and network access. The CLI does not read `.env`: in a full `pytest` run the key is picked up from `.env` because the web-app tests import the app, but running that test alone needs the variable exported in your shell.

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.
