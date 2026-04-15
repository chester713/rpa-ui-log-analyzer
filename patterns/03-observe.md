# Pattern: Observe

## Action
Observe

## Object
Element

## Method
HTML DOM parsing (Web) / UI Automation tree parsing (Desktop) / Visual recognition (Visual)

## Category
Extraction

## Contexts
- web
- desktop
- visual

## Description
The Observe pattern enables a bot to monitor a target object for state changes over time. Unlike the Read Element pattern, which performs a one-time extraction of a value, the Observe pattern continuously monitors the target over time, capturing dynamic UI changes as they occur.

This pattern has three variants:
1. HTML element → HTML DOM parsing → Web environment
2. UI element → UI Automation tree parsing → Web/Desktop environment
3. Visual element → Visual recognition → Web/Desktop/Screen environment

## Applicability
- The target element must be successfully identified
- The automation environment allows reading data through DOM interfaces, accessibility frameworks, or screen-scraping services
- If using visual recognition methods, the target element must be unobstructed
- Continuous monitoring or event-driven observation is feasible

## Operation
The bot continuously monitors the object to detect state or property changes through polling or event-driven mechanisms, ensuring subsequent actions are triggered only when the required transition occurs.