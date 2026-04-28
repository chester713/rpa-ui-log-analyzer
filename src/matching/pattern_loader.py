"""Pattern loader for reading pattern .md files."""

import os
import re
from typing import List
from ..models.pattern import Pattern


class PatternLoader:
    """Loads RPA patterns from skill.md files."""

    def load_patterns(self, patterns_dir: str = "patterns") -> List[Pattern]:
        """
        Load all pattern .md files from the patterns directory.

        Args:
            patterns_dir: Directory containing pattern .md files

        Returns:
            List of Pattern objects
        """
        patterns = self._load_from_markdown_dir(patterns_dir)
        if patterns:
            return patterns

        # Backward-compatible fallback if caller passes a non-existent dir.
        return self._load_from_markdown_dir("patterns")

    def _load_from_markdown_dir(self, path: str) -> List[Pattern]:
        patterns = []
        if not os.path.exists(path):
            return patterns

        for filename in sorted(os.listdir(path)):
            if filename.endswith(".md"):
                filepath = os.path.join(path, filename)
                pattern = self._parse_pattern_file(filepath)
                if pattern:
                    patterns.append(pattern)

        return patterns

    def _parse_pattern_file(self, filepath: str) -> Pattern:
        """
        Parse a pattern .md file to extract pattern fields.

        Args:
            filepath: Path to the .md file

        Returns:
            Pattern object
        """
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        name = self._extract_section(content, "Pattern:") or os.path.basename(
            filepath
        ).replace(".md", "")
        action = self._extract_section(content, "Action")
        obj = self._extract_section(content, "Object")
        method = self._extract_section(content, "Method")
        category = self._extract_section(content, "Category")
        contexts_str = self._extract_section(content, "Contexts") or ""

        contexts = []
        for ctx in ["web", "desktop", "screen"]:
            if ctx in contexts_str.lower():
                contexts.append(ctx)

        description = self._extract_section(content, "Description") or ""

        return Pattern(
            name=name.strip(),
            action=action.strip() if action else "",
            object=obj.strip() if obj else "",
            method=method.strip() if method else "",
            category=category.strip() if category else "Extraction",
            contexts=contexts,
            description=description.strip(),
        )

    def _extract_section(self, content: str, section_name: str) -> str:
        """Extract content after a section header."""
        pattern = rf"{re.escape(section_name)}\s*(.*?)(?=\n##|\Z)"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""
