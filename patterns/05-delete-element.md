# Pattern: Delete Element

## Action
Delete

## Object
Element

## Method
HTML DOM manipulation (Web) / UI Automation manipulation (Desktop) / Hardware simulation (Visual)

## Category
Modification

## Contexts
- web
- desktop
- screen

## Description
This pattern enables a bot to delete a target UI element, or a piece of the content it holds, such as text in a text field. Unlike the Write element pattern, whose purpose is to put data into an element, the Delete element pattern takes something away: the element itself or part of its content.

This pattern covers two scenarios:
1. Deleting an element: the element is removed from the DOM or UI hierarchy, for example a window.
2. Deleting content from an element: the element stays and the data it holds is removed, for example the text in a text field. Replacing the content with new data is a Write.

This pattern has three variants:
1. HTML element → HTML DOM manipulation → Web environment
2. UI element → UI Automation manipulation → Web/Desktop environment
3. Visual element → Hardware simulation → Web/Desktop/Screen environment

## Applicability
- The element is programmatically identifiable in the DOM (web) or UI automation tree (desktop), or visually identifiable on the screen
- The automation environment supports deletion via DOM access, accessibility-level operations or virtual keystrokes
- To delete content, the element is editable, such as a text field that is not read-only
- For hardware simulation, the element is focused for input so that the delete keystrokes reach it

## Operation
Once the target UI element is identified, the bot uses the corresponding method.
- To delete an element, it removes the element from the DOM or UI hierarchy, ensuring subsequent actions operate on a clean interface.
- To delete content, it clears the value of the element through DOM manipulation, or sets the value to empty through UI Automation manipulation. With hardware simulation, it first sets the focus on the element and then sends virtual delete keystrokes (Delete, Backspace), selecting the text to be deleted first where necessary. When the deletion is completed, the bot removes focus from the element to register the change.
