# Pattern: Disable Element

## Action
Disable

## Object
Element

## Method
HTML DOM manipulation (Web) / UI Automation tree manipulation (Desktop) / Hardware simulation (Visual)

## Category
Modification

## Contexts
- web
- desktop
- screen

## Description
This pattern enables a bot to deactivate or suppress a target element without removing it from the UI hierarchy. It modifies the state of an element so that it no longer interferes with task execution. Typical use cases include suppressing pop-ups, overlays, or modal dialogues.

This pattern has three variants:
1. HTML element → HTML DOM manipulation → Web environment
2. UI element → UI Automation tree manipulation → Web/Desktop environment
3. Visual element → Hardware simulation → Web/Desktop/Screen environment

## Operation
- **Web**: Modify element's CSS properties (e.g., visibility: hidden) to suppress the element
- **Desktop**: Use accessibility-level operations to invoke interface controls to turn the element into an inactive state (e.g., pressing a close button)
- **Screen**: Visually identify the interfering element, locate its close button, and send a virtual mouse click