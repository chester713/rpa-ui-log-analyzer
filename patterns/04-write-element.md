# Pattern: Write Element

## Action
Write

## Object
Element

## Method
DOM manipulation (Web) / UI Automation manipulation (Desktop) / Hardware simulation (Visual)

## Category
Modification

## Contexts
- web
- desktop
- screen

## Description
This pattern enables a bot to write, update, or insert data into a target UI element exposed through the application interface. It operationalises content modification within the user interface.

This pattern has three variants:
1. HTML element → DOM manipulation (script injection) → Web environment
2. UI element → UI Automation manipulation → Web/Desktop environment
3. Visual element → Hardware simulation → Web/Desktop/Screen environment

## Applicability
- A writable interface element exists
- The element is successfully identified and activated for input
- At least one input method is feasible

## Operation
After locating the target element, the bot uses an appropriate writing strategy. It may directly assign the value through DOM or UI Automation manipulation, or simulate virtual keystrokes. When input is completed, the bot removes focus from the element to register the updated input.