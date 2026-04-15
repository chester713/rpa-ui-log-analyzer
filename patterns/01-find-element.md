# Pattern: Find Element

## Action
Find

## Object
Element

## Method
DOM parsing (Web) / UIA Tree Parsing (Desktop) / Visual Recognition (Visual)

## Category
Extraction

## Contexts
- web
- desktop
- visual

## Description
The Find Element pattern enables a bot to establish a reference to a target UI element. Within the AOMC model, Find Element represents an interaction action that connects a bot to an interaction object through context-dependent identification methods.

This pattern has three variants:
1. HTML element → DOM parsing → Web environment
2. UI element → UI Automation tree parsing → Web/Desktop environment
3. Visual element → Visual recognition → Web/Desktop/Screen environment

## Applicability
- The bot must be capable of executing JavaScript or other scripts
- The bot must be capable of executing accessibility patterns to UI hierarchy
- The bot must be capable of conducting image recognition
- If the target object is an HTML element, the webpage must be fully loaded