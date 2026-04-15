# Pattern: Delete Element

## Action
Delete

## Object
Element

## Method
HTML DOM manipulation (Web) / UI Automation manipulation (Desktop)

## Category
Modification

## Contexts
- web
- desktop

## Description
This pattern enables a bot to remove a target element from the DOM or UI hierarchy. Unlike the Write element pattern, which modifies content (content-level modification), the Delete element pattern performs structural manipulation by eliminating the element itself.

This pattern has two variants:
1. HTML element → HTML DOM manipulation → Web environment
2. UI element → UI Automation manipulation → Web/Desktop environment

Note: This pattern does NOT apply to visual/screen environments.

## Applicability
- The element is programmatically identifiable in the DOM (web) or UI automation tree (desktop)
- The automation environment supports structural manipulation via DOM access or accessibility-level operations
- Does NOT apply in screen-based/visual environments

## Operation
Once the target UI element is identified, the bot uses the corresponding method to remove the element from the DOM or UI hierarchy, ensuring subsequent actions operate on a clean interface.