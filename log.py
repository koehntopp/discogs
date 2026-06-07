# /// script
# dependencies = ["structlog"]
# ///

import sys
import os
import logging
import structlog

# Allow config.py to live outside the scripts directory (e.g. /config in Docker).
_config_dir = os.environ.get('CONFIG_DIR')
if _config_dir and _config_dir not in sys.path:
	sys.path.insert(0, _config_dir)

SUCCESS = 25  # between INFO (20) and WARNING (30)
logging.addLevelName(SUCCESS, 'SUCCESS')

_shared_processors = [
	structlog.stdlib.add_log_level,
	structlog.processors.TimeStamper(fmt='%H:%M:%S'),
	structlog.processors.StackInfoRenderer(),
]

structlog.configure(
	processors=_shared_processors + [
		structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
	],
	logger_factory=structlog.stdlib.LoggerFactory(),
	wrapper_class=structlog.stdlib.BoundLogger,
	cache_logger_on_first_use=True,
)

_is_tty = sys.stderr.isatty()

if _is_tty:
	# Interactive terminal: pretty coloured output to stderr
	_console_handler = logging.StreamHandler(sys.stderr)
	_console_handler.setFormatter(
		structlog.stdlib.ProcessorFormatter(
			processor=structlog.dev.ConsoleRenderer(),
			foreign_pre_chain=_shared_processors,
		)
	)
else:
	# Running as a subprocess: JSON to stdout so the parent can capture and re-log
	_console_handler = logging.StreamHandler(sys.stdout)
	_console_handler.setFormatter(
		structlog.stdlib.ProcessorFormatter(
			processor=structlog.processors.JSONRenderer(),
			foreign_pre_chain=_shared_processors,
		)
	)

_root = logging.getLogger()
_root.addHandler(_console_handler)
_root.setLevel(logging.INFO)

try:
	from config import log_file, log_rotation, log_retention
	try:
		from config import config_dir
	except ImportError:
		config_dir = '.'
	from pathlib import Path
	_log_path = Path(os.environ.get('CONFIG_DIR') or config_dir) / log_file
	_log_path.parent.mkdir(parents=True, exist_ok=True)
	_file_handler = logging.FileHandler(str(_log_path), encoding='utf-8')
	_file_handler.setFormatter(
		structlog.stdlib.ProcessorFormatter(
			processor=structlog.processors.JSONRenderer(),
			foreign_pre_chain=_shared_processors,
		)
	)
	_root.addHandler(_file_handler)
except Exception:
	pass  # log to console only if config is missing or broken


logger = structlog.get_logger()


def success(msg: str, **kw) -> None:
	"""Log at SUCCESS level (green in the UI, between INFO and WARNING)."""
	logging.getLogger().log(SUCCESS, msg, **kw)
