# Pattern: Refresh

## Action
Refresh

## Object
Element

## Method
HTML DOM manipulation (Web) / UI Automation tree manipulation (Desktop) / Hardware simulation (Visual)

## Category
Control

## Contexts
- web
- desktop
- screen

## Description
This pattern enables a bot to update or reload the current state of a user interface element or view to reflect the most recent data. Refreshing triggers a re-render or re-query of UI content.

This pattern has three variants:
1. HTML element → HTML DOM manipulation → Web environment
2. UI element → UI Automation tree manipulation → Web/Desktop environment
3. Visual element → Hardware simulation → Web/Desktop/Screen environment

## Operation
- Web: JavaScript execution triggering DOM updates or page reload (location.reload())
- Desktop: UI Automation patterns for update/refresh behaviours
- Visual: Hardware input simulation (mouse clicks or keyboard inputs to activate refresh control)