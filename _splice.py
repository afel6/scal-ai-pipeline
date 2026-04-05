"""Splice _build_docx_new.py into document_engines.py, replacing build_docx()."""
import pathlib

root = pathlib.Path(r'c:\Users\Asus\Downloads\scal-ai-pipeline')

new_func = (root / '_build_docx_new.py').read_text(encoding='utf-8')
engine   = (root / 'document_engines.py').read_text(encoding='utf-8')

START_MARKER = '\n    @staticmethod\n    def build_docx('
END_MARKER   = '\n\n    @staticmethod\n    def build_excel('

start = engine.find(START_MARKER)
end   = engine.find(END_MARKER)

if start == -1 or end == -1:
    raise RuntimeError(f'Markers not found: start={start} end={end}')

new_engine = engine[:start] + new_func + engine[end:]
(root / 'document_engines.py').write_text(new_engine, encoding='utf-8')
print(f'Spliced successfully. New size: {len(new_engine)} chars.')

# Verify it parses
import py_compile, sys, tempfile, os
tmp = tempfile.NamedTemporaryFile(suffix='.py', delete=False, mode='w', encoding='utf-8')
tmp.write(new_engine); tmp.close()
try:
    py_compile.compile(tmp.name, doraise=True)
    print('Syntax OK.')
except py_compile.PyCompileError as e:
    print(f'SYNTAX ERROR: {e}')
finally:
    os.unlink(tmp.name)
