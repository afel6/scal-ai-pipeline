import pytest
from scal_file_handler import fix_markdown_spacing

class TestFixMarkdownSpacing:

    def test_empty_input(self):
        assert fix_markdown_spacing("") == ""
        assert fix_markdown_spacing(None) is None

    def test_heading_padding_needed(self):
        # Missing newline before heading
        text = "Some text## Heading 2"
        assert fix_markdown_spacing(text) == "Some text\n\n## Heading 2"

        # Only one newline before heading
        text = "Some text\n### Heading 3"
        assert fix_markdown_spacing(text) == "Some text\n\n### Heading 3"

    def test_heading_padding_already_correct(self):
        # Proper double newline before heading
        text = "Some text\n\n## Heading 2"
        assert fix_markdown_spacing(text) == "Some text\n\n## Heading 2"

        # Starts with heading (no previous text, no need to pad before start of string in markdown renderer)
        # However, regex `([^\n])\s*(#{2,}\s)` matches single chars. Let's see what happens if it starts with heading.
        text = "## Heading at start"
        assert fix_markdown_spacing(text) == "## Heading at start"

    def test_table_padding_needed(self):
        # No preceding newline
        text = "Some text| Col 1 | Col 2 |"
        assert fix_markdown_spacing(text) == "Some text\n\n| Col 1 | Col 2 |"

        # Only one newline
        text = "Some text\n| Col 1 | Col 2 |"
        assert fix_markdown_spacing(text) == "Some text\n\n| Col 1 | Col 2 |"

    def test_table_padding_already_correct(self):
        text = "Some text\n\n| Col 1 | Col 2 |"
        assert fix_markdown_spacing(text) == "Some text\n\n| Col 1 | Col 2 |"

    def test_table_concatenation_fix(self):
        # Two tables glued together
        text = "| Col 1 | Col 2 | | Val 1 | Val 2 |"
        assert fix_markdown_spacing(text) == "| Col 1 | Col 2 |\n| Val 1 | Val 2 |"

        # Trailing spaces between them
        text = "| Col 1 | Col 2 |   | Val 1 | Val 2 |"
        assert fix_markdown_spacing(text) == "| Col 1 | Col 2 |\n| Val 1 | Val 2 |"

    def test_edge_case_plain_text_with_pipe(self):
        # Plain text containing a pipe shouldn't have newlines inserted before the pipe
        text = "I like cats | dogs"
        assert fix_markdown_spacing(text) == "I like cats | dogs"

        text = "Option A | Option B\nLine 2"
        assert fix_markdown_spacing(text) == "Option A | Option B\nLine 2"

    def test_edge_case_table_with_empty_cells(self):
        # Empty cells shouldn't have their spaces crushed into a newline
        text = "| Col 1 | Col 2 |\n|   | Val 2 |"
        assert fix_markdown_spacing(text) == "| Col 1 | Col 2 |\n|   | Val 2 |"

        text = "| Col A |   | Col C |"
        assert fix_markdown_spacing(text) == "| Col A |   | Col C |"
