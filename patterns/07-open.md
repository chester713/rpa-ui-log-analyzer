# Pattern: Open

## Action
Open

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
The Open pattern captures actions that create a new software instance to enable access to a file, application, or web page. Unlike the Activate pattern, which triggers functional behaviour of an already available element, the Open pattern establishes the required context for subsequent interactions.

This pattern has three variants:
1. HTML element → HTML DOM manipulation → Web environment
2. UI element → UI Automation manipulation → Web/Desktop environment
3. Visual element → Hardware simulation → Web/Desktop/Screen environment

## Operation
The bot establishes a new execution context for the target resource using an appropriate interaction method (script-based interactions, structured automation interfaces, or hardware simulation).