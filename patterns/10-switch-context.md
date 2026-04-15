# Pattern: Switch Context

## Action
Switch

## Object
Context

## Method
UI Automation manipulation (Desktop) / Hardware simulation (Desktop)

## Category
Control

## Contexts
- desktop

## Description
The Switch Context pattern enables the bot to change its active execution context between different applications, windows, or containers. This allows the bot to continue interacting with UI elements that reside within another context.

This pattern has two variants:
1. UI element → UI Automation manipulation → Desktop environment
2. UI element → Hardware simulation → Desktop environment

Note: Automatically handled by OS when using DOM/UI Automation methods. Primarily required for hardware simulation.

## Applicability
- Bot requires operating on more than one execution contexts
- Bot can access all execution contexts required
- NOT applicable when interactions occur within same context (e.g., navigating containers on same web page)

## Operation
The bot invokes appropriate method to switch the active context to the target context, identified using application windows, browser handles, or tab references.