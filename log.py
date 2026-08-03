#!/usr/bin/env -S uv run
# /// script
# dependencies = ["structlog"]
# ///

import logging
import os
import sys

import structlog

# Allow config.py to live outside the scripts directory (e.g. /config in Docker).
_config_dir = os.environ.get('CONFIG_DIR')
if _config_dir and _config_dir not in sys.path:
	sys.path.insert(0, _config_dir)

SUCCESS = 25  # between INFO (20) and WARNING (30)
logging.addLevelName(SUCCESS, 'SUCCESS')


# Add success method to standard logging.Logger so stdlib wrappers can delegate success() calls
def _logging_success(self, msg, *args, **kwargs):
	if self.isEnabledFor(SUCCESS):
		self._log(SUCCESS, msg, args, **kwargs)


logging.Logger.success = _logging_success


# Register success level inside structlog internal mappings
try:
	import structlog.stdlib

	structlog.stdlib.NAME_TO_LEVEL['success'] = SUCCESS
	structlog.stdlib.LEVEL_TO_NAME[SUCCESS] = 'success'
except AttributeError:
	pass


class CustomBoundLogger(structlog.stdlib.BoundLogger):
	def success(self, event=None, *args, **kw):
		return self.log(SUCCESS, event, *args, **kw)


_shared_processors = [
	structlog.stdlib.add_log_level,
	structlog.processors.TimeStamper(fmt='%H:%M:%S'),
	structlog.processors.StackInfoRenderer(),
]

structlog.configure(
	processors=_shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
	logger_factory=structlog.stdlib.LoggerFactory(),
	wrapper_class=CustomBoundLogger,
	cache_logger_on_first_use=True,
)


_is_tty = sys.stderr.isatty()

if _is_tty:
	# Interactive terminal: pretty coloured output to stderr
	_level_styles = {
		**structlog.dev.ConsoleRenderer.get_default_level_styles(),
		'info': structlog.dev.RESET_ALL,
		'success': '\033[32m',  # green
	}
	_console_handler = logging.StreamHandler(sys.stderr)
	_console_handler.setFormatter(
		structlog.stdlib.ProcessorFormatter(
			processor=structlog.dev.ConsoleRenderer(level_styles=_level_styles),
			foreign_pre_chain=_shared_processors,
		)
	)
else:
	# Running as a subprocess: JSON to stdout so the parent can capture and re-log
	_console_handler = logging.StreamHandler(sys.stdout)
	_console_handler.setFormatter(
		structlog.stdlib.ProcessorFormatter(
			processor=structlog.processors.JSONRenderer(), foreign_pre_chain=_shared_processors
		)
	)


def parse_log_level(val: str | int) -> int:
	if isinstance(val, int):
		return val
	s = str(val).upper().strip()
	if s == 'SUCCESS':
		return SUCCESS
	return getattr(logging, s, logging.INFO)


_log_level_env = os.environ.get('LOG_LEVEL')
_log_level_cfg = None

try:
	from config import log_level as _cfg_level

	_log_level_cfg = _cfg_level
except ImportError:
	pass

_active_level = parse_log_level(_log_level_env or _log_level_cfg or 'INFO')

_root = logging.getLogger()
_root.addHandler(_console_handler)
_root.setLevel(_active_level)


def set_log_level(level_name_or_int: str | int) -> None:
	"""Set active log level dynamically (e.g. 'SUCCESS' to hide INFO logs)."""
	_root.setLevel(parse_log_level(level_name_or_int))


logging.getLogger('matplotlib').setLevel(logging.WARNING)
logging.getLogger('PIL').setLevel(logging.WARNING)

if not os.environ.get('DISCOGS_CHILD'):
	# Skip file logging in child processes spawned by webui — the parent captures
	# their stdout and re-logs, so writing to the file here would double every line.
	try:
		from config import log_file

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
				processor=structlog.processors.JSONRenderer(), foreign_pre_chain=_shared_processors
			)
		)
		_root.addHandler(_file_handler)
	except Exception:
		pass  # log to console only if config is missing or broken


if not os.environ.get('DISCOGS_CHILD'):
	try:
		from logging.handlers import SysLogHandler

		from config import syslog_host, syslog_port

		class _SafeSysLogHandler(SysLogHandler):
			def emit(self, record):
				try:
					super().emit(record)
				except Exception:
					pass

		_syslog_handler = _SafeSysLogHandler(address=(syslog_host, int(syslog_port)))
		_syslog_handler.setFormatter(logging.Formatter('discogs %(levelname)s %(message)s'))
		_root.addHandler(_syslog_handler)
	except ImportError:
		pass
	except Exception:
		pass


logger = structlog.get_logger()


def success(msg: str, **kw) -> None:
	"""Log at SUCCESS level (green in the UI, between INFO and WARNING)."""
	logging.getLogger().log(SUCCESS, msg, **kw)
