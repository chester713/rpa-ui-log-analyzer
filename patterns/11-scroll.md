# Pattern: Scroll

## Action
Scroll

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
The Scroll pattern enables the bot to perform scrolling actions to reveal UI elements that are not currently visible within the viewport.

This pattern has three variants:
1. HTML element → HTML DOM manipulation → Web environment
2. UI element → UI Automation tree manipulation → Web/Desktop environment
3. Visual element → Hardware simulation → Web/Desktop/Screen environment

Note: May not be required when DOM-based methods are available (can access elements without visibility).

## Applicability
- Target element is currently not visible and cannot be interacted with
- Target element is located in a scrollable region (web page, document)

## Operation
The bot identifies the scrollable container, determines scrolling direction, performs scrolling actions (UI Automation control or hardware simulation), and iterates until target element is revealed.