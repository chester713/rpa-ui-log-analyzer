# Pattern: Activate

## Action
Activate

## Object
Element

## Method
HTML DOM manipulation (Web) / UI Automation manipulation (Desktop) / Hardware simulation (Visual)

## Category
Control

## Contexts
- web
- desktop
- visual

## Description
This pattern enables a bot to trigger or invoke the functional behaviour of a user interface element. Activation corresponds to executing an action associated with an interactive control, such as clicking a button, selecting a menu item, opening a link, or confirming an operation.

This pattern has three variants:
1. HTML element → HTML DOM manipulation → Web environment
2. UI element → UI Automation manipulation → Web/Desktop environment
3. Visual element → Hardware simulation → Web/Desktop/Screen environment

## Applicability
- The target element represents an actionable control (button, hyperlink, menu item, checkbox)
- The element is successfully identified
- The automation environment allows interaction through exposed interface structures or input simulation

## Operation
The bot triggers activation through DOM events (click()), UI Automation patterns (InvokePattern.Invoke()), or hardware simulation (mouse clicks at screen location).