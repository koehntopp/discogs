#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "structlog",
# ]
# ///

"""check_docs.py — Fail when the lrc_fix.py documentation has drifted from the code.

Checks (see CLAUDE.md, "lrc_fix.py / lrc_format.py Documentation Map"):
  1. every command-line flag defined in lrc_fix.py appears in the options table of
     README-lrc_fix.md, and the table lists no flag that lrc_fix.py no longer has;
  2. every dependency pinned in lrc_fix.py's PEP 723 header appears, with the same version
     specifier, on the "Dependencies" line of the lrc_fix.py section of SPEC.md, and that line
     lists nothing that is no longer pinned.

Usage:
    uv run check_docs.py

Exits 0 when everything matches, 1 otherwise.
"""

import ast
import re
import sys
from pathlib import Path

from log import logger

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'lrc_fix.py'
README = ROOT / 'README-lrc_fix.md'
SPEC = ROOT / 'SPEC.md'


def script_flags(source: str) -> set[str]:
	"""Long flags passed to add_argument(); argparse's implicit --help is not documented."""
	flags: set[str] = set()
	for node in ast.walk(ast.parse(source)):
		is_add = (
			isinstance(node, ast.Call)
			and isinstance(node.func, ast.Attribute)
			and node.func.attr == 'add_argument'
		)
		if not is_add:
			continue
		for arg in node.args:
			if (
				isinstance(arg, ast.Constant)
				and isinstance(arg.value, str)
				and arg.value.startswith('--')
			):
				flags.add(arg.value)
	return flags


def readme_flags(text: str) -> set[str]:
	"""Flags in the first column of the table under '### Options'."""
	match = re.search(r'^### Options\s*$(.*?)(?=^#{1,3} )', text, re.MULTILINE | re.DOTALL)
	if not match:
		raise ValueError("no '### Options' section in README-lrc_fix.md")
	return set(re.findall(r'^\|\s*`(--[a-z0-9-]+)`', match.group(1), re.MULTILINE))


def script_pins(source: str) -> set[str]:
	"""Dependency specifiers from the PEP 723 header, e.g. 'torch>=2.4,<2.6'."""
	block = re.search(r'^# /// script\s*$(.*?)^# ///\s*$', source, re.MULTILINE | re.DOTALL)
	if not block:
		raise ValueError('no PEP 723 header in lrc_fix.py')
	deps = re.search(r'dependencies\s*=\s*\[(.*?)\]', block.group(1).replace('# ', ''), re.DOTALL)
	if not deps:
		raise ValueError('no dependencies list in the lrc_fix.py header')
	return set(re.findall(r'["\']([^"\']+)["\']', deps.group(1)))


def spec_pins(text: str) -> set[str]:
	"""Backticked entries on the 'Dependencies' line of the lrc_fix.py section of SPEC.md."""
	section = re.search(r'^### `lrc_fix\.py`.*?(?=^### `)', text, re.MULTILINE | re.DOTALL)
	if not section:
		raise ValueError('no lrc_fix.py section in SPEC.md')
	line = re.search(r'^\*\*Dependencies:\*\*(.*)$', section.group(0), re.MULTILINE)
	if not line:
		raise ValueError("no '**Dependencies:**' line in the lrc_fix.py section of SPEC.md")
	return set(re.findall(r'`([^`]+)`', line.group(1)))


def compare(label: str, code: set[str], docs: set[str], where: str) -> list[str]:
	problems = []
	for item in sorted(code - docs):
		problems.append(f'{label} {item} is in lrc_fix.py but missing from {where}')
	for item in sorted(docs - code):
		problems.append(f'{label} {item} is listed in {where} but not in lrc_fix.py')
	return problems


def main() -> int:
	source = SCRIPT.read_text(encoding='utf-8')
	try:
		problems = compare(
			'flag',
			script_flags(source),
			readme_flags(README.read_text(encoding='utf-8')),
			'the README-lrc_fix.md options table',
		)
		problems += compare(
			'dependency',
			script_pins(source),
			spec_pins(SPEC.read_text(encoding='utf-8')),
			'the SPEC.md lrc_fix.py Dependencies line',
		)
	except (OSError, ValueError) as exc:
		logger.error(f'check_docs: cannot run the check: {exc}')
		return 1
	for problem in problems:
		logger.error(f'docs out of sync: {problem}')
	if problems:
		return 1
	logger.success('lrc_fix.py docs are in sync (flags and dependency pins)')
	return 0


if __name__ == '__main__':
	sys.exit(main())
