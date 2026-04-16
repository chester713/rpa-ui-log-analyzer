---
wave: 1
depends_on: []
files_modified:
  - app.py
  - templates/index.html
  - templates/results.html
  - templates/settings.html
  - templates/history.html
  - data/history.json
  - config/llm_config.json
  - skills/recommend.md
requirements_addressed:
  - REQ-10
  - REQ-11
  - REQ-12
autonomous: false
---

# Phase 4: Web Portal

## Objective

Build a browser-based Flask web application for UI log upload and recommendations display with configurable LLM support and file-based history.

---

## Tasks

### Task 1: Flask App Setup

<read_first>
- .planning/ROADMAP.md
- .planning/phases/03-cli-integration/src/analyzer.py
</read_first>

<action>
Create Flask app structure in project root:
- Create app.py with Flask application
- Create config/ directory with default LLM config
- Create data/ directory for history storage
- Create templates/ directory for HTML templates
- Install flask: pip install flask
</action>

<acceptance_criteria>
- app.py contains Flask app with route handlers
- config/llm_config.json exists with default settings
- data/ directory exists
- templates/ directory exists
- flask is installable via pip
</acceptance_criteria>

---

### Task 2: File Upload & Results Display (REQ-10)

<read_first>
- app.py (created in Task 1)
</read_first>

<action>
Implement file upload endpoint:
- POST /analyze accepts CSV file upload
- Parse CSV using Phases 1-3 logic (import from existing modules)
- Return results with activity-method mapping
- Create templates/index.html with file upload form
- Create templates/results.html with recommendations display
- Implement GET /history to list past analyses
</action>

<acceptance_criteria>
- POST /analyze returns JSON with activity, method, and mapping
- index.html has file input with accept=".csv"
- results.html displays activity name, recommended method, event mapping
- GET /history returns list of past analyses from data/history.json
</acceptance_criteria>

---

### Task 3: LLM Configuration Panel (REQ-11)

<read_first>
- config/llm_config.json
</read_first>

<action>
Implement settings panel:
- GET /settings returns LLM configuration page
- POST /settings updates LLM provider and API key
- Support two modes: Puter.js (no API key) OR custom OpenAI-compatible endpoint
- Create templates/settings.html with configuration form
</action>

<acceptance_criteria>
- config/llm_config.json contains: provider (puter/custom), endpoint (if custom), api_key (masked)
- /settings page shows current provider
- /settings form allows selecting Puter.js or entering custom endpoint + API key
- POST /settings validates and saves config
</acceptance_criteria>

---

### Task 4: History Persistence

<read_first>
- data/history.json (empty or existing)
</read_first>

<action>
Implement analysis history:
- On POST /analyze, save result to history
- History entry: timestamp, filename, activity, method, mapping
- GET /history shows table of past analyses
- GET /history/<id> shows specific result
- Create data/history.json with simple JSON array structure
</action>

<acceptance_criteria>
- data/history.json is valid JSON array
- New analyses are appended to data/history.json
- /history shows table with timestamp, filename, activity, method columns
- /history/<id> returns single analysis result
</acceptance_criteria>

---

### Task 5: Skill-Based Pattern System (REQ-12)

<read_first>
- .planning/phases/02-pattern-system/src/patterns.json
</read_first>

<action>
Migrate patterns to skill format:
- Create skills/recommend.md skill file
- Store pattern definitions as skill.md
- Recommendation logic as separate skill
- patterns.json moved to skills/patterns.md
- Update analyzer to load patterns from skills/ directory
</action>

<acceptance_criteria>
- skills/recommend.md exists with recommendation logic
- skills/patterns.md exists with pattern definitions
- Analyzer imports from skills/ directory
- skills/ directory is loaded before analysis
</acceptance_criteria>

---

## Verification

<must_haves>
- User can upload CSV through web interface
- Recommendations displayed with activity-method mapping
- LLM settings panel allows switching between Puter.js and custom endpoint
- Past analyses viewable in history page
- Patterns stored as skill.md files
</must_haves>

---

## Notes

- Phase 1-3 modules imported for analysis logic
- Puter.js as default no-key LLM option
- File-based persistence (no database)
- Single-page application structure