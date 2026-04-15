# Pattern: Read Element

## Action
Read

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
This pattern enables a bot to read the attributes or properties of a target element. It operationalises data extraction within the user interface by allowing bots to retrieve information from specific elements.

This pattern has three variants:
1. HTML element → HTML DOM parsing → Web environment
2. UI element → UI Automation tree parsing → Web/Desktop environment
3. Visual element → Visual recognition → Web/Desktop/Screen environment

## Applicability
- The target element must be successfully identified
- The automation environment allows reading data through DOM interfaces, accessibility frameworks, or screen-scraping services
- If using visual recognition methods, the target element must be unobstructed and rendered visibly on the computer screen

## Operation
After locating the target element, the bot uses an appropriate automation method to extract the desired property from the element. The extracted data can be stored in a temporary variable or saved to a file.