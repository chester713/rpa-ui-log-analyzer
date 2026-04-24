# Pattern: Hover

## Action
Hover

## Object
Element

## Method
HTML DOM manipulation (Web) / Hardware simulation (Web/Desktop/Screen)

## Category
Control

## Contexts
- web
- desktop
- visual

## Description
The Hover pattern captures actions where the bot positions the pointer over a target element to trigger context-dependent UI behaviour (tooltips, pop-ups, dynamic menus). Unlike activation, hovering does not alter the application state.

This pattern has two variants:
1. HTML element → HTML DOM manipulation → Web environment
2. Visual element → Hardware simulation → Web/Desktop/Screen environment

Note: UI Automation patterns do not natively support hover execution.

## Applicability
- Required data or UI elements are not present in static DOM/visible UI state
- Target element provides hover-enabled functionality
- Bot can interact with UI elements triggered by hover action

## Operation
The bot performs the hover action by dispatching mouseover event via JavaScript or simulates pointer movement through hardware simulation.