# Pattern: Focus

## Action
Focus

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
The Focus pattern enables the bot to set the input focus on a target UI element, allowing it to receive subsequent input actions. Unlike Activate, Focus assigns input focus without invoking any associated behaviour.

This pattern has three variants:
1. HTML element → HTML DOM manipulation → Web environment
2. UI element → UI Automation tree manipulation → Web/Desktop environment
3. Visual element → Hardware simulation → Web/Desktop/Screen environment

## Applicability
- Bot requires focusing on designated element to enable subsequent data entry
- Element is not automatically focused and requires dedicated focus action

## Operation
- Web: DOM manipulation (element.focus)
- Desktop: UI Automation tree manipulation (SetFocus)
- Visual: Hardware simulation (mouse clicks, Tab keystroke)