# Skill: Activity-to-Method Recommendation

## Purpose
This skill provides the logic for mapping inferred activities to RPA automation methods.

## Input
- Inferred Activity: Action + Object from AOMC vocabulary
- Execution Context: web / desktop / visual
- Event Attributes: Context information supporting the inference

## Output
- Recommended Method: The automation method to use
- Method Category: Extraction / Modification

## Logic

### Step 1: Context Detection
Detect execution context from event attributes:
- `webpage`, `url` → web
- `app`, `application` → desktop
- `element_type` (image, icon) → visual

### Step 2: Activity-to-Pattern Matching
Match activity (Action + Object) to pattern name:
- `Find + Element` → "Find Element"
- `Read + Element` → "Read Element"
- `Write + Element` → "Write Element"
- `Activate + Element` → "Activate"
- `Select + Option` → "Select Option"
- etc.

### Step 3: Method Selection
Select method based on context:
| Pattern | Web | Desktop | Visual |
|---------|-----|---------|--------|
| Find Element | DOM Parsing | UIA Tree Parsing | Visual Recognition |
| Read Element | DOM Parsing | UIA Tree Parsing | Visual Recognition |
| Write Element | DOM Manipulation | UIA Manipulation | Hardware Simulation |
| Activate | DOM Manipulation | UIA Manipulation | Hardware Simulation |
| Select Option | DOM Manipulation | UIA Manipulation | Hardware Simulation |
| etc. | | | |

### Step 4: Context Switch Detection
Detect application changes:
- Different `application` or `app` attribute → Context switch occurred
- Note: For structured methods (DOM/UIA), context switch is handled by OS
- Note: For unstructured methods (Visual/Hardware), explicit Switch Context action needed

## Categories

### Extraction Methods
- DOM Parsing
- UIA Tree Parsing
- Visual Recognition
- Hardware Simulation

### Modification Methods
- DOM Manipulation
- UIA Tree Manipulation
- Hardware Simulation

## Usage
This skill is used by the pattern matcher to recommend methods based on:
1. Inferred activity (from activity inference)
2. Execution context (from event attributes)
3. Context switches (from application changes)