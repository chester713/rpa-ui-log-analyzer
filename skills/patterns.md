# Skill: RPA UI Interaction Patterns

This skill contains the complete library of 13 RPA UI interaction patterns.

## Pattern Structure
Each pattern has:
- **Action**: The verb from AOMC vocabulary
- **Object**: The noun from AOMC vocabulary  
- **Method**: The RPA method for each context
- **Category**: Extraction or Modification
- **Contexts**: List of valid execution contexts

---

## Extraction Patterns

### Pattern 1: Find Element
- **Action**: Find
- **Object**: Element
- **Method**: 
  - Web: DOM Parsing
  - Desktop: UIA Tree Parsing
  - Visual: Visual Recognition
- **Category**: Extraction
- **Contexts**: web, desktop, visual

### Pattern 2: Read Element
- **Action**: Read
- **Object**: Element
- **Method**:
  - Web: HTML DOM Parsing
  - Desktop: UI Automation Tree Parsing
  - Visual: Visual Recognition
- **Category**: Extraction
- **Contexts**: web, desktop, visual

### Pattern 3: Observe
- **Action**: Observe
- **Object**: Element
- **Method**:
  - Web: HTML DOM Parsing
  - Desktop: UI Automation Tree Parsing
  - Visual: Visual Recognition
- **Category**: Extraction
- **Contexts**: web, desktop, visual

---

## Modification Patterns

### Pattern 4: Write Element
- **Action**: Write
- **Object**: Element
- **Method**:
  - Web: DOM Manipulation (script injection)
  - Desktop: UI Automation Manipulation
  - Visual: Hardware Simulation
- **Category**: Modification
- **Contexts**: web, desktop, visual

### Pattern 5: Delete Element
- **Action**: Delete
- **Object**: Element
- **Method**:
  - Web: HTML DOM Manipulation
  - Desktop: UI Automation Manipulation
- **Category**: Modification
- **Contexts**: web, desktop
- **Note**: Not applicable to visual environments

### Pattern 6: Disable Element
- **Action**: Disable
- **Object**: Element
- **Method**:
  - Web: HTML DOM Manipulation
  - Desktop: UI Automation Tree Manipulation
  - Visual: Hardware Simulation
- **Category**: Modification
- **Contexts**: web, desktop, visual

---

## Control Patterns

### Pattern 7: Open
- **Action**: Open
- **Object**: Element
- **Method**:
  - Web: HTML DOM Manipulation
  - Desktop: UI Automation Manipulation
  - Visual: Hardware Simulation
- **Category**: Control
- **Contexts**: web, desktop, visual

### Pattern 8: Activate
- **Action**: Activate
- **Object**: Element
- **Method**:
  - Web: HTML DOM Manipulation
  - Desktop: UI Automation Manipulation
  - Visual: Hardware Simulation
- **Category**: Control
- **Contexts**: web, desktop, visual

### Pattern 9: Hover
- **Action**: Hover
- **Object**: Element
- **Method**:
  - Web: HTML DOM Manipulation
  - Visual: Hardware Simulation
- **Category**: Control
- **Contexts**: web, desktop, visual
- **Note**: UI Automation does not natively support hover

### Pattern 10: Switch Context
- **Action**: Switch
- **Object**: Context
- **Method**:
  - Desktop: UI Automation Manipulation
  - Desktop: Hardware Simulation
- **Category**: Control
- **Contexts**: desktop
- **Note**: Automatically handled by OS for structured methods; required for hardware simulation

### Pattern 11: Scroll
- **Action**: Scroll
- **Object**: Element
- **Method**:
  - Web: HTML DOM Manipulation
  - Desktop: UI Automation Tree Manipulation
  - Visual: Hardware Simulation
- **Category**: Control
- **Contexts**: web, desktop, visual

### Pattern 12: Focus
- **Action**: Focus
- **Object**: Element
- **Method**:
  - Web: HTML DOM Manipulation
  - Desktop: UI Automation Tree Manipulation
  - Visual: Hardware Simulation
- **Category**: Control
- **Contexts**: web, desktop, visual

### Pattern 13: Refresh
- **Action**: Refresh
- **Object**: Element
- **Method**:
  - Web: HTML DOM Manipulation
  - Desktop: UI Automation Tree Manipulation
  - Visual: Hardware Simulation
- **Category**: Control
- **Contexts**: web, desktop, visual

---

## Usage
Load these patterns for activity-to-method matching. The matcher should:
1. Parse inferred activity name into Action + Object
2. Find matching pattern by Action + Object
3. Select method based on execution context
4. Return Method + Category