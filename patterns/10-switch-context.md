# Pattern: Switch Context

## Action
Switch context

## Object
UI element

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

Note: Context switching is automatically handled by the OS when structured methods (DOM manipulation and UI Automation manipulation) are used. This pattern is particularly required when using hardware simulation methods.

## Applicability
- The bot requires operating on more than one execution context
- The bot can access all execution contexts required
- NOT applicable when interactions occur within the same execution context (e.g., navigating between containers on the same web page, or visual regions within the same screen)

## Operation
When required, the bot invokes an appropriate method to switch the currently active context to the target context. The target context can be identified using available identifiers such as application windows, browser handles, or tab references. Upon completion, the bot may verify that the target context is active before proceeding with subsequent actions.

## Example
A bot transfers customer data from an Excel workbook to a web-based CRM system. After retrieving the required data from the spreadsheet, the bot invokes hardware simulation (virtual keyboard shortcut Alt+Tab) to switch to the browser. After confirming the browser is the active context and the URL is correct, the bot proceeds to locate the input field for data entry.
